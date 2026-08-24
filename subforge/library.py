from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Callable
from uuid import uuid4

LIBRARY_SCHEMA_VERSION = 1
ITEM_SCHEMA_VERSION = 1
SUPPORTED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac"}
SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v"}
_RJ_RE = re.compile(r"^RJ\d+$", re.IGNORECASE)


class ItemKind(StrEnum):
    RJ_WORK = "rj_work"
    STREAM_ARCHIVE = "stream_archive"


class CreatorKind(StrEnum):
    CIRCLE = "circle"
    VOICE_ACTOR = "voice_actor"


@dataclass(frozen=True)
class Creator:
    creator_id: str
    name: str
    kind: CreatorKind
    last_used_at: str | None = None


@dataclass(frozen=True)
class ImportSource:
    source_id: str
    url: str
    source_type: str
    imported_at: str
    track_ids: list[str]


@dataclass(frozen=True)
class ImportRequest:
    source: Path
    kind: ItemKind
    title: str
    rj_code: str | None = None
    author: str | None = None
    creator_ids: tuple[str, ...] = ()
    source_url: str | None = None
    archive_name: str | None = None
    original_relative_path: str | None = None
    source_language: str = "ja"
    target_language: str = "zh"


@dataclass(frozen=True)
class ImportResult:
    item_id: str
    track_id: str
    created: bool


@dataclass(frozen=True)
class FolderMediaEntry:
    source: Path
    relative_path: str
    media_type: str
    archive_name: str


@dataclass(frozen=True)
class FolderScanResult:
    root: Path
    media: list[FolderMediaEntry]
    skipped: list[str]

    @property
    def audio_count(self) -> int:
        return sum(entry.media_type == "audio" for entry in self.media)

    @property
    def video_count(self) -> int:
        return sum(entry.media_type == "video" for entry in self.media)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)


@dataclass(frozen=True)
class FolderImportResult:
    status: str
    item_id: str | None
    imported_count: int
    duplicate_count: int
    skipped_count: int
    failed_count: int
    failures: list[dict[str, str]]
    imported_track_ids: tuple[str, ...] = ()


@dataclass
class Track:
    track_id: str
    media: str
    sha256: str
    size: int
    source_language: str = "ja"
    target_language: str = "zh"
    status: str = "waiting"
    original_relative_path: str | None = None


@dataclass
class LibraryItem:
    schema_version: int
    item_id: str
    kind: ItemKind
    title: str
    rj_code: str | None = None
    author: str | None = None
    creator_ids: list[str] = field(default_factory=list)
    sources: list[ImportSource] = field(default_factory=list)
    cover_source: str | None = None
    created_at: str = ""
    updated_at: str = ""
    tracks: list[Track] = field(default_factory=list)
    directory: str = ""


ProgressCallback = Callable[[int, int], None]


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _safe_name(value: str, fallback: str = "untitled") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", value).strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:100] or fallback


def _natural_key(value: str) -> tuple:
    return tuple(int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", value))


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
    _fsync_directory(path.parent)


class LibraryStore:
    """Own Library file safety, metadata and rebuildable indexing."""

    def __init__(self, root: Path, connection: sqlite3.Connection) -> None:
        self.root = root.resolve()
        self._db = connection
        self._db.row_factory = sqlite3.Row
        self._db_lock = threading.RLock()

    @classmethod
    def initialize(cls, root: Path) -> "LibraryStore":
        root = root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        for name in ("works", "streams", ".incoming", ".trash", ".subforge"):
            (root / name).mkdir(parents=True, exist_ok=True)
        library_path = root / "library.json"
        if not library_path.exists():
            _atomic_json(library_path, {
                "schema_version": LIBRARY_SCHEMA_VERSION,
                "library_id": uuid4().hex,
                "created_at": _now(),
            })
        return cls._open_connection(root)

    @classmethod
    def open(cls, root: Path) -> "LibraryStore":
        root = root.resolve()
        if not (root / "library.json").is_file():
            raise ValueError(f"Not a SubForge Library: {root}")
        for name in ("works", "streams", ".incoming", ".trash", ".subforge"):
            (root / name).mkdir(parents=True, exist_ok=True)
        return cls._open_connection(root)

    @classmethod
    def _open_connection(cls, root: Path) -> "LibraryStore":
        db_path = root / ".subforge" / "index.sqlite"
        try:
            connection = sqlite3.connect(db_path, check_same_thread=False)
            store = cls(root, connection)
            store._create_schema()
            store.sync_index()
            return store
        except sqlite3.DatabaseError:
            try:
                connection.close()
            except Exception:
                pass
            if db_path.exists():
                db_path.replace(db_path.with_suffix(f".damaged-{uuid4().hex[:8]}.sqlite"))
            connection = sqlite3.connect(db_path, check_same_thread=False)
            store = cls(root, connection)
            store._create_schema()
            store.rebuild_index()
            return store

    def close(self) -> None:
        with self._db_lock:
            self._db.close()

    def _create_schema(self) -> None:
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS items (
                item_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                rj_code TEXT,
                author TEXT,
                directory TEXT NOT NULL UNIQUE,
                metadata_mtime_ns INTEGER NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS item_rj_code
                ON items(rj_code) WHERE rj_code IS NOT NULL;
            CREATE TABLE IF NOT EXISTS tracks (
                track_id TEXT PRIMARY KEY,
                item_id TEXT NOT NULL,
                media TEXT NOT NULL,
                sha256 TEXT NOT NULL UNIQUE,
                size INTEGER NOT NULL,
                source_language TEXT NOT NULL,
                target_language TEXT NOT NULL,
                status TEXT NOT NULL,
                FOREIGN KEY(item_id) REFERENCES items(item_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                track_id TEXT NOT NULL,
                status TEXT NOT NULL,
                stage TEXT,
                progress REAL NOT NULL DEFAULT 0,
                completed INTEGER,
                total INTEGER,
                message TEXT,
                config_snapshot TEXT,
                updated_at TEXT NOT NULL
            );
        """)
        self._db.commit()

    def _metadata_paths(self) -> list[Path]:
        paths = list((self.root / "works").glob("*/metadata.json"))
        paths += list((self.root / "streams").glob("*/*/metadata.json"))
        return paths

    def sync_index(self) -> None:
        """Incrementally synchronize metadata changed since the last scan."""
        metadata_paths = self._metadata_paths()
        relative_paths = {path.parent.relative_to(self.root).as_posix(): path for path in metadata_paths}
        with self._db_lock:
            rows = self._db.execute("SELECT directory, metadata_mtime_ns FROM items").fetchall()
        indexed = {row["directory"]: row["metadata_mtime_ns"] for row in rows}
        with self._db_lock, self._db:
            for directory in set(indexed) - set(relative_paths):
                row = self._db.execute("SELECT item_id FROM items WHERE directory=?", (directory,)).fetchone()
                if row:
                    self._db.execute("DELETE FROM tracks WHERE item_id=?", (row["item_id"],))
                    self._db.execute("DELETE FROM items WHERE item_id=?", (row["item_id"],))
        for directory, metadata_path in relative_paths.items():
            if indexed.get(directory) == metadata_path.stat().st_mtime_ns:
                continue
            try:
                item = self._read_item(metadata_path)
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                continue
            self._index_item(item, metadata_path)

    def rebuild_index(self) -> None:
        metadata_paths = self._metadata_paths()
        with self._db_lock, self._db:
            self._db.execute("DELETE FROM tracks")
            self._db.execute("DELETE FROM items")
        for metadata_path in metadata_paths:
            try:
                item = self._read_item(metadata_path)
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                continue
            self._index_item(item, metadata_path)

    def list_items(self, creator_ids: list[str] | None = None) -> list[LibraryItem]:
        with self._db_lock:
            rows = self._db.execute("SELECT directory FROM items ORDER BY title COLLATE NOCASE").fetchall()
        items = [self._read_item(self.root / row["directory"] / "metadata.json") for row in rows]
        required = set(creator_ids or [])
        if required:
            items = [item for item in items if required.issubset(item.creator_ids)]
        return items

    @property
    def _creators_path(self) -> Path:
        return self.root / ".subforge" / "creators.json"

    def list_creators(self) -> list[Creator]:
        if not self._creators_path.exists():
            return []
        data = json.loads(self._creators_path.read_text(encoding="utf-8"))
        creators = [Creator(
            creator_id=str(entry["creator_id"]),
            name=str(entry["name"]),
            kind=CreatorKind(entry["kind"]),
            last_used_at=entry.get("last_used_at"),
        ) for entry in data.get("creators", [])]
        creators.sort(key=lambda creator: (creator.name.casefold(), creator.kind.value, creator.creator_id))
        creators.sort(key=lambda creator: creator.last_used_at or "", reverse=True)
        return creators

    def create_creator(self, name: str, kind: CreatorKind) -> Creator:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("creator name is required")
        creator = Creator(uuid4().hex, clean_name, CreatorKind(kind))
        creators = self.list_creators()
        creators.append(creator)
        self._write_creators(creators)
        return creator

    def update_creator(self, creator_id: str, *, name: str) -> Creator:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("creator name is required")
        creators = self.list_creators()
        for index, creator in enumerate(creators):
            if creator.creator_id == creator_id:
                updated = Creator(creator.creator_id, clean_name, creator.kind, creator.last_used_at)
                creators[index] = updated
                self._write_creators(creators)
                return updated
        raise KeyError(creator_id)

    def touch_creators(self, creator_ids: list[str]) -> None:
        selected = set(creator_ids)
        if not selected:
            return
        now = _now()
        creators = self.list_creators()
        known = {creator.creator_id for creator in creators}
        if not selected.issubset(known):
            raise ValueError("unknown creator")
        self._write_creators([
            Creator(creator.creator_id, creator.name, creator.kind, now)
            if creator.creator_id in selected else creator
            for creator in creators
        ])

    def delete_creator(self, creator_id: str) -> None:
        if any(creator_id in item.creator_ids for item in self.list_items()):
            raise ValueError("creator is still associated with Library Items")
        creators = self.list_creators()
        remaining = [creator for creator in creators if creator.creator_id != creator_id]
        if len(remaining) == len(creators):
            raise KeyError(creator_id)
        self._write_creators(remaining)

    def merge_creators(self, source_id: str, target_id: str) -> Creator:
        if source_id == target_id:
            raise ValueError("source and target creators must be different")
        creators = {creator.creator_id: creator for creator in self.list_creators()}
        try:
            source, target = creators[source_id], creators[target_id]
        except KeyError as exc:
            raise KeyError(str(exc)) from exc
        if source.kind != target.kind:
            raise ValueError("creators with different kinds cannot be merged")
        for item in self.list_items():
            if source_id not in item.creator_ids:
                continue
            item.creator_ids = list(dict.fromkeys(
                target_id if creator_id == source_id else creator_id
                for creator_id in item.creator_ids
            ))
            item.author = self._legacy_author(item.creator_ids)
            item.updated_at = _now()
            item_dir = self.root / item.directory
            self._write_item(item_dir, item)
            self._index_item(item, item_dir / "metadata.json")
        self._write_creators([creator for creator in creators.values() if creator.creator_id != source_id])
        return target

    def update_item(
        self,
        item_id: str,
        *,
        title: str,
        kind: ItemKind,
        rj_code: str | None,
        creator_ids: list[str],
    ) -> LibraryItem:
        item = self.get_item(item_id)
        clean_title = title.strip()
        if not clean_title:
            raise ValueError("title is required")
        kind = ItemKind(kind)
        creators = {creator.creator_id: creator for creator in self.list_creators()}
        normalized_ids = list(dict.fromkeys(creator_ids))
        try:
            selected = [creators[creator_id] for creator_id in normalized_ids]
        except KeyError as exc:
            raise ValueError("unknown creator") from exc
        if kind == ItemKind.RJ_WORK:
            normalized_rj = (rj_code or "").strip().upper()
            if not _RJ_RE.fullmatch(normalized_rj):
                raise ValueError("valid RJ code is required")
            with self._db_lock:
                duplicate = self._db.execute(
                    "SELECT item_id FROM items WHERE rj_code=? AND item_id<>?",
                    (normalized_rj, item_id),
                ).fetchone()
            if duplicate:
                raise ValueError("RJ code already exists")
        else:
            normalized_rj = None
            if not selected or any(creator.kind != CreatorKind.VOICE_ACTOR for creator in selected):
                raise ValueError("stream archives require voice actors only")
        item.title = clean_title
        item.kind = kind
        item.rj_code = normalized_rj
        item.creator_ids = normalized_ids
        item.author = self._legacy_author(normalized_ids)
        self.touch_creators(normalized_ids)
        item.updated_at = _now()
        item_dir = self.root / item.directory
        self._write_item(item_dir, item)
        self._index_item(item, item_dir / "metadata.json")
        return item

    def _write_creators(self, creators: list[Creator]) -> None:
        _atomic_json(self._creators_path, {
            "creators": [
                {
                    "creator_id": creator.creator_id,
                    "name": creator.name,
                    "kind": creator.kind.value,
                    "last_used_at": creator.last_used_at,
                }
                for creator in creators
            ]
        })

    def _find_or_create_creator(self, name: str, kind: CreatorKind) -> Creator:
        clean_name = name.strip()
        for creator in self.list_creators():
            if creator.name.casefold() == clean_name.casefold() and creator.kind == kind:
                return creator
        return self.create_creator(clean_name, kind)

    def _resolve_creators(self, creator_ids: list[str]) -> list[Creator]:
        creators = {creator.creator_id: creator for creator in self.list_creators()}
        try:
            return [creators[creator_id] for creator_id in creator_ids]
        except KeyError as exc:
            raise ValueError("unknown creator") from exc

    def _legacy_author(self, creator_ids: list[str]) -> str | None:
        names = [creator.name for creator in self._resolve_creators(creator_ids)]
        return ", ".join(names) or None

    def get_item(self, item_id: str) -> LibraryItem:
        with self._db_lock:
            row = self._db.execute("SELECT directory FROM items WHERE item_id = ?", (item_id,)).fetchone()
        if row is None:
            raise KeyError(item_id)
        return self._read_item(self.root / row["directory"] / "metadata.json")

    def get_track(self, track_id: str) -> tuple[LibraryItem, Track]:
        with self._db_lock:
            row = self._db.execute(
                "SELECT i.item_id FROM tracks t JOIN items i ON i.item_id=t.item_id WHERE t.track_id=?",
                (track_id,),
            ).fetchone()
        if row is None:
            raise KeyError(track_id)
        item = self.get_item(row["item_id"])
        track = next(track for track in item.tracks if track.track_id == track_id)
        return item, track

    def item_directory(self, item_id: str) -> Path:
        with self._db_lock:
            row = self._db.execute("SELECT directory FROM items WHERE item_id=?", (item_id,)).fetchone()
        if row is None:
            raise KeyError(item_id)
        return self._inside_root(self.root / row["directory"])

    def track_media_path(self, track_id: str) -> Path:
        item, track = self.get_track(track_id)
        return self._inside_root(self.root / item.directory / track.media)

    def track_subtitle_path(self, track_id: str, language: str) -> Path:
        item, track = self.get_track(track_id)
        media = Path(track.media)
        return self._inside_root(
            self.root / item.directory / "subtitles" / f"{media.stem}.{language}.srt"
        )

    def track_resume_dir(self, track_id: str) -> Path:
        item, _ = self.get_track(track_id)
        path = self._inside_root(self.root / item.directory / ".subforge" / "tracks")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def import_audio(
        self,
        request: ImportRequest,
        progress_callback: ProgressCallback | None = None,
    ) -> ImportResult:
        source = request.source.resolve()
        self._validate_request(request, source)
        import_id = uuid4().hex
        archive_name = _safe_name(request.archive_name or source.name, source.name)
        incoming = self.root / ".incoming" / import_id
        incoming_media = incoming / "media"
        incoming_media.mkdir(parents=True, exist_ok=False)
        partial = incoming_media / f"{archive_name}.part"
        digest = hashlib.sha256()
        copied = 0
        total = source.stat().st_size
        try:
            with source.open("rb") as reader, partial.open("xb") as writer:
                while chunk := reader.read(1024 * 1024):
                    writer.write(chunk)
                    digest.update(chunk)
                    copied += len(chunk)
                    if progress_callback:
                        progress_callback(copied, total)
                writer.flush()
                os.fsync(writer.fileno())
            checksum = digest.hexdigest()
            with self._db_lock:
                duplicate = self._db.execute(
                    "SELECT item_id, track_id FROM tracks WHERE sha256=?", (checksum,)
                ).fetchone()
            if duplicate is not None:
                shutil.rmtree(incoming, ignore_errors=True)
                return ImportResult(duplicate["item_id"], duplicate["track_id"], False)

            existing_item = self._find_existing_item(request)
            track = Track(
                track_id=uuid4().hex,
                media=f"media/{archive_name}",
                sha256=checksum,
                size=total,
                source_language=request.source_language,
                target_language=request.target_language,
                original_relative_path=request.original_relative_path,
            )
            if existing_item is not None:
                item_dir = self.root / existing_item.directory
                destination = item_dir / track.media
                if destination.exists():
                    raise ValueError(f"A different Track already uses filename {archive_name!r}")
                partial.replace(destination)
                existing_item.tracks.append(track)
                if request.source_url:
                    existing_item.sources.append(self._new_import_source(request.source_url, track.track_id))
                existing_item.updated_at = _now()
                self._write_item(item_dir, existing_item)
                shutil.rmtree(incoming, ignore_errors=True)
                self._index_item(existing_item, item_dir / "metadata.json")
                return ImportResult(existing_item.item_id, track.track_id, True)

            item = self._new_item(request, track)
            item_dir = self.root / item.directory
            if item_dir.exists():
                raise ValueError(f"Library directory already exists: {item.directory}")
            (incoming / "subtitles").mkdir()
            (incoming / ".subforge" / "tracks").mkdir(parents=True)
            partial.replace(incoming / "media" / archive_name)
            self._write_item(incoming, item)
            item_dir.parent.mkdir(parents=True, exist_ok=True)
            incoming.replace(item_dir)
            self._index_item(item, item_dir / "metadata.json")
            return ImportResult(item.item_id, track.track_id, True)
        except Exception:
            # Keep interrupted imports inspectable; retry starts with a new import id.
            raise

    def scan_rj_folder(self, folder: Path) -> FolderScanResult:
        root = folder.resolve()
        if not root.is_dir():
            raise ValueError("folder must be an existing directory")
        media: list[FolderMediaEntry] = []
        skipped: list[str] = []
        for source in sorted((path for path in root.rglob("*") if path.is_file()), key=lambda path: _natural_key(path.relative_to(root).as_posix())):
            relative = source.relative_to(root).as_posix()
            extension = source.suffix.lower()
            if extension in SUPPORTED_AUDIO_EXTENSIONS:
                media_type = "audio"
                archive_name = source.name
            elif extension in SUPPORTED_VIDEO_EXTENSIONS:
                media_type = "video"
                archive_name = f"{source.stem}.m4a"
            else:
                skipped.append(relative)
                continue
            media.append(FolderMediaEntry(source, relative, media_type, _safe_name(archive_name)))

        grouped: dict[str, list[int]] = {}
        for index, entry in enumerate(media):
            grouped.setdefault(entry.archive_name.casefold(), []).append(index)
        used: set[str] = set()
        resolved = list(media)
        for indexes in grouped.values():
            for index in indexes:
                entry = media[index]
                candidate = entry.archive_name
                if len(indexes) > 1:
                    parents = list(Path(entry.relative_path).parent.parts)
                    prefix_parts: list[str] = []
                    for part in reversed(parents):
                        prefix_parts.insert(0, _safe_name(part))
                        candidate = f"{'_'.join(prefix_parts)}_{entry.archive_name}"
                        if candidate.casefold() not in used:
                            break
                candidate = self._unique_archive_name(candidate, used)
                used.add(candidate.casefold())
                resolved[index] = FolderMediaEntry(
                    entry.source, entry.relative_path, entry.media_type, candidate,
                )
        resolved.sort(key=lambda entry: _natural_key(entry.relative_path))
        return FolderScanResult(root=root, media=resolved, skipped=skipped)

    def import_rj_folder(
        self,
        folder: Path,
        *,
        rj_code: str,
        title: str | None = None,
        creator_ids: tuple[str, ...] = (),
        progress_callback: Callable[[dict], None] | None = None,
    ) -> FolderImportResult:
        normalized_rj = rj_code.strip().upper()
        if not _RJ_RE.fullmatch(normalized_rj):
            raise ValueError("valid RJ code is required")
        scan = self.scan_rj_folder(folder)
        resolved_title = (title or "").strip() or normalized_rj
        existing = self._find_existing_item(ImportRequest(
            source=folder, kind=ItemKind.RJ_WORK, title=resolved_title, rj_code=normalized_rj,
        ))
        item_id = existing.item_id if existing else None
        used_names = {Path(track.media).name.casefold() for track in existing.tracks} if existing else set()
        imported = duplicates = failed = 0
        imported_track_ids: list[str] = []
        failures: list[dict[str, str]] = []
        temporary_root = Path(tempfile.mkdtemp(prefix="subforge-folder-import-"))
        total = len(scan.media)
        try:
            for index, entry in enumerate(scan.media, start=1):
                if progress_callback:
                    progress_callback({
                        "stage": "convert" if entry.media_type == "video" else "import",
                        "current": entry.relative_path,
                        "completed": index - 1,
                        "total": total,
                        "imported": imported,
                        "duplicates": duplicates,
                        "failed": failed,
                    })
                source = entry.source
                try:
                    if entry.media_type == "video":
                        source = temporary_root / f"{uuid4().hex}.m4a"
                        self._convert_video_to_m4a(entry.source, source)
                    archive_name = self._unique_archive_name(entry.archive_name, used_names)
                    result = self.import_audio(ImportRequest(
                        source=source,
                        kind=ItemKind.RJ_WORK,
                        title=resolved_title,
                        rj_code=normalized_rj,
                        archive_name=archive_name,
                        original_relative_path=entry.relative_path,
                        creator_ids=creator_ids,
                    ))
                    item_id = result.item_id
                    if result.created:
                        imported += 1
                        imported_track_ids.append(result.track_id)
                        used_names.add(archive_name.casefold())
                    else:
                        duplicates += 1
                except (ValueError, OSError, subprocess.SubprocessError) as exc:
                    failed += 1
                    failures.append({"path": entry.relative_path, "error": str(exc)})
            if item_id is not None:
                item = self.get_item(item_id)
                if creator_ids:
                    item = self.update_item(
                        item_id, title=item.title, kind=ItemKind.RJ_WORK,
                        rj_code=item.rj_code, creator_ids=list(dict.fromkeys([*item.creator_ids, *creator_ids])),
                    )
                item.tracks.sort(key=lambda track: _natural_key(track.original_relative_path or track.media))
                item.updated_at = _now()
                item_dir = self.root / item.directory
                self._write_item(item_dir, item)
                self._index_item(item, item_dir / "metadata.json")
        finally:
            shutil.rmtree(temporary_root, ignore_errors=True)
        if progress_callback:
            progress_callback({
                "stage": "complete", "completed": total, "total": total,
                "imported": imported, "duplicates": duplicates, "failed": failed,
            })
        if imported and failed:
            status = "partial"
        elif imported:
            status = "completed"
        else:
            status = "failed" if failed else "completed"
        return FolderImportResult(
            status=status, item_id=item_id, imported_count=imported,
            duplicate_count=duplicates, skipped_count=scan.skipped_count,
            failed_count=failed, failures=failures,
            imported_track_ids=tuple(imported_track_ids),
        )

    def _convert_video_to_m4a(self, source: Path, destination: Path) -> None:
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            raise ValueError("ffmpeg is required to import video files")
        result = subprocess.run([
            ffmpeg, "-y", "-loglevel", "error", "-i", str(source),
            "-vn", "-c:a", "aac", "-b:a", "192k", str(destination),
        ], capture_output=True, timeout=1800)
        if result.returncode != 0 or not destination.exists() or destination.stat().st_size == 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip()[-300:]
            raise ValueError(f"video audio conversion failed: {detail or 'unknown ffmpeg error'}")

    @staticmethod
    def _unique_archive_name(name: str, used: set[str]) -> str:
        candidate = _safe_name(name)
        if candidate.casefold() not in used:
            return candidate
        path = Path(candidate)
        index = 2
        while True:
            numbered = f"{path.stem} ({index}){path.suffix}"
            if numbered.casefold() not in used:
                return numbered
            index += 1

    def prepare_processing(self, track_id: str, mode: str) -> None:
        """Prepare resume/subtitles for continue, retranslate, or from-scratch."""
        if mode == "continue":
            return
        item, track = self.get_track(track_id)
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        languages = [track.target_language]
        if mode == "from_scratch":
            languages.insert(0, track.source_language)
        elif mode != "retranslate":
            raise ValueError("mode must be continue, retranslate, or from_scratch")
        for language in languages:
            path = self.track_subtitle_path(track_id, language)
            if path.exists():
                backup = path.with_name(f"{path.name}.bak-{timestamp}")
                path.replace(backup)
        resume_dir = self.track_resume_dir(track_id)
        for state_file in resume_dir.glob("*.json"):
            state_file.unlink()
        track.status = "waiting"
        item.updated_at = _now()
        item_dir = self.root / item.directory
        self._write_item(item_dir, item)
        self._index_item(item, item_dir / "metadata.json")

    def rename_track(self, track_id: str, filename: str) -> Track:
        item, track = self.get_track(track_id)
        current = Path(track.media)
        cleaned = _safe_name(filename, current.name)
        candidate = Path(cleaned)
        if candidate.name != cleaned:
            raise ValueError("filename must not contain a directory")
        if candidate.suffix.lower() != current.suffix.lower():
            raise ValueError(f"filename must keep the {current.suffix} extension")
        if candidate.name == current.name:
            return track

        item_dir = self.root / item.directory
        old_media = self._inside_root(item_dir / track.media)
        new_media = self._inside_root(item_dir / "media" / candidate.name)
        if new_media.exists():
            raise ValueError(f"A different Track already uses filename {candidate.name!r}")

        old_stem = current.stem
        new_stem = candidate.stem
        subtitle_moves: list[tuple[Path, Path]] = []
        subtitle_dir = item_dir / "subtitles"
        for source in subtitle_dir.glob(f"{old_stem}.*.srt*"):
            destination = source.with_name(new_stem + source.name[len(old_stem):])
            if destination.exists():
                raise ValueError(f"Subtitle filename already exists: {destination.name}")
            subtitle_moves.append((source, destination))

        moved: list[tuple[Path, Path]] = []
        try:
            old_media.replace(new_media)
            moved.append((new_media, old_media))
            for source, destination in subtitle_moves:
                source.replace(destination)
                moved.append((destination, source))
            track.media = f"media/{candidate.name}"
            item.updated_at = _now()
            self._write_item(item_dir, item)
            self._index_item(item, item_dir / "metadata.json")
            self._delete_track_resume_states(track_id, item_dir)
            return track
        except Exception:
            for source, destination in reversed(moved):
                if source.exists() and not destination.exists():
                    source.replace(destination)
            raise

    def trash_track(self, track_id: str) -> None:
        item, track = self.get_track(track_id)
        item_dir = self.root / item.directory
        media_path = self._inside_root(item_dir / track.media)
        stem = Path(track.media).stem
        target = self.root / ".trash" / f"track-{track_id}-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        target.mkdir(parents=True, exist_ok=False)
        if media_path.exists():
            media_path.replace(target / media_path.name)
        subtitle_dir = item_dir / "subtitles"
        for subtitle in subtitle_dir.glob(f"{stem}.*.srt*"):
            subtitle.replace(target / subtitle.name)
        self._delete_track_resume_states(track_id, item_dir)
        item.tracks = [candidate for candidate in item.tracks if candidate.track_id != track_id]
        item.sources = [
            ImportSource(
                source_id=source.source_id,
                url=source.url,
                source_type=source.source_type,
                imported_at=source.imported_at,
                track_ids=[value for value in source.track_ids if value != track_id],
            )
            for source in item.sources
        ]
        item.updated_at = _now()
        self._write_item(item_dir, item)
        self._index_item(item, item_dir / "metadata.json")
        with self._db_lock, self._db:
            self._db.execute("DELETE FROM tasks WHERE track_id=?", (track_id,))

    def _delete_track_resume_states(self, track_id: str, item_dir: Path) -> None:
        resume_dir = item_dir / ".subforge" / "tracks"
        for state_path in resume_dir.glob("*.json"):
            try:
                data = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if data.get("media", {}).get("path") == track_id:
                state_path.unlink(missing_ok=True)

    def trash_item(self, item_id: str) -> None:
        item_dir = self.item_directory(item_id)
        target = self.root / ".trash" / f"{item_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        item_dir.replace(target)
        with self._db_lock, self._db:
            self._db.execute("DELETE FROM tracks WHERE item_id=?", (item_id,))
            self._db.execute("DELETE FROM items WHERE item_id=?", (item_id,))

    def update_track_status(self, track_id: str, status: str) -> None:
        item, track = self.get_track(track_id)
        track.status = status
        item.updated_at = _now()
        item_dir = self.root / item.directory
        self._write_item(item_dir, item)
        self._index_item(item, item_dir / "metadata.json")

    def set_cover_source(self, item_id: str, source: str) -> None:
        item = self.get_item(item_id)
        item.cover_source = source
        item.updated_at = _now()
        item_dir = self.root / item.directory
        self._write_item(item_dir, item)
        self._index_item(item, item_dir / "metadata.json")

    def _validate_request(self, request: ImportRequest, source: Path) -> None:
        if not source.is_file():
            raise ValueError("source must be an existing file")
        if source.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
            raise ValueError("source must be a supported audio file")
        if not request.title.strip():
            raise ValueError("title is required")
        if request.kind == ItemKind.RJ_WORK:
            if not request.rj_code or not _RJ_RE.fullmatch(request.rj_code):
                raise ValueError("valid RJ code is required")
        elif request.kind == ItemKind.STREAM_ARCHIVE:
            selected = self._resolve_creators(list(request.creator_ids))
            if selected and any(creator.kind != CreatorKind.VOICE_ACTOR for creator in selected):
                raise ValueError("stream archives require voice actors only")
            if not selected and (not request.author or not request.author.strip()):
                raise ValueError("author is required for stream archive")
        else:
            raise ValueError("unsupported item kind")

    def _find_existing_item(self, request: ImportRequest) -> LibraryItem | None:
        if request.kind != ItemKind.RJ_WORK:
            return None
        with self._db_lock:
            row = self._db.execute(
                "SELECT item_id FROM items WHERE rj_code=?", (request.rj_code.upper(),)
            ).fetchone()
        return self.get_item(row["item_id"]) if row else None

    def _new_item(self, request: ImportRequest, track: Track) -> LibraryItem:
        item_id = uuid4().hex
        now = _now()
        if request.kind == ItemKind.RJ_WORK:
            rj_code = request.rj_code.upper()
            directory = f"works/{rj_code}"
        else:
            rj_code = None
            selected = self._resolve_creators(list(request.creator_ids))
            primary_name = selected[0].name if selected else (request.author or "unknown")
            author = _safe_name(primary_name, "unknown")
            title = _safe_name(request.title)
            directory = f"streams/{author}/{title}-{item_id[:6]}"
        creator_ids = list(dict.fromkeys(request.creator_ids))
        self._resolve_creators(creator_ids)
        if not creator_ids and request.author and request.author.strip():
            creator = self._find_or_create_creator(request.author, CreatorKind.VOICE_ACTOR)
            creator_ids.append(creator.creator_id)
        self.touch_creators(creator_ids)
        sources = [self._new_import_source(request.source_url, track.track_id)] if request.source_url else []
        return LibraryItem(
            schema_version=ITEM_SCHEMA_VERSION,
            item_id=item_id,
            kind=request.kind,
            title=request.title.strip(),
            rj_code=rj_code,
            author=self._legacy_author(creator_ids) or (request.author.strip() if request.author else None),
            creator_ids=creator_ids,
            sources=sources,
            cover_source=None,
            created_at=now,
            updated_at=now,
            tracks=[track],
            directory=directory,
        )

    def _new_import_source(self, url: str, track_id: str) -> ImportSource:
        return ImportSource(
            source_id=uuid4().hex,
            url=url.strip(),
            source_type="url",
            imported_at=_now(),
            track_ids=[track_id],
        )

    def _write_item(self, item_dir: Path, item: LibraryItem) -> None:
        data = asdict(item)
        data["kind"] = item.kind.value
        # Directory is index context, not an internal asset path.
        data.pop("directory", None)
        _atomic_json(item_dir / "metadata.json", data)

    def _read_item(self, metadata_path: Path) -> LibraryItem:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
        if int(data["schema_version"]) != ITEM_SCHEMA_VERSION:
            raise ValueError("unsupported item schema")
        directory = metadata_path.parent.relative_to(self.root).as_posix()
        creator_ids = [str(value) for value in data.get("creator_ids", [])]
        author = data.get("author")
        if not creator_ids and author and str(author).strip():
            creator = self._find_or_create_creator(str(author), CreatorKind.VOICE_ACTOR)
            creator_ids = [creator.creator_id]
        return LibraryItem(
            schema_version=int(data["schema_version"]),
            item_id=str(data["item_id"]),
            kind=ItemKind(data["kind"]),
            title=str(data["title"]),
            rj_code=data.get("rj_code"),
            author=author,
            creator_ids=creator_ids,
            sources=[ImportSource(**source) for source in data.get("sources", [])],
            cover_source=data.get("cover_source"),
            created_at=str(data["created_at"]),
            updated_at=str(data["updated_at"]),
            tracks=[Track(**track) for track in data.get("tracks", [])],
            directory=directory,
        )

    def _index_item(self, item: LibraryItem, metadata_path: Path) -> None:
        with self._db_lock, self._db:
            self._db.execute(
                """INSERT OR REPLACE INTO items
                   (item_id, kind, title, rj_code, author, directory, metadata_mtime_ns)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    item.item_id, item.kind.value, item.title, item.rj_code, item.author,
                    item.directory, metadata_path.stat().st_mtime_ns,
                ),
            )
            self._db.execute("DELETE FROM tracks WHERE item_id=?", (item.item_id,))
            for track in item.tracks:
                self._db.execute(
                    """INSERT OR REPLACE INTO tracks
                       (track_id,item_id,media,sha256,size,source_language,target_language,status)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        track.track_id, item.item_id, track.media, track.sha256, track.size,
                        track.source_language, track.target_language, track.status,
                    ),
                )

    def _inside_root(self, path: Path) -> Path:
        resolved = path.resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise ValueError("Library path escapes root")
        return resolved
