from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
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
_RJ_RE = re.compile(r"^RJ\d+$", re.IGNORECASE)


class ItemKind(StrEnum):
    RJ_WORK = "rj_work"
    STREAM_ARCHIVE = "stream_archive"


@dataclass(frozen=True)
class ImportRequest:
    source: Path
    kind: ItemKind
    title: str
    rj_code: str | None = None
    author: str | None = None
    source_language: str = "ja"
    target_language: str = "zh"


@dataclass(frozen=True)
class ImportResult:
    item_id: str
    track_id: str
    created: bool


@dataclass
class Track:
    track_id: str
    media: str
    sha256: str
    size: int
    source_language: str = "ja"
    target_language: str = "zh"
    status: str = "waiting"


@dataclass
class LibraryItem:
    schema_version: int
    item_id: str
    kind: ItemKind
    title: str
    rj_code: str | None = None
    author: str | None = None
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

    def list_items(self) -> list[LibraryItem]:
        with self._db_lock:
            rows = self._db.execute("SELECT directory FROM items ORDER BY title COLLATE NOCASE").fetchall()
        return [self._read_item(self.root / row["directory"] / "metadata.json") for row in rows]

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
        incoming = self.root / ".incoming" / import_id
        incoming_media = incoming / "media"
        incoming_media.mkdir(parents=True, exist_ok=False)
        partial = incoming_media / f"{source.name}.part"
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
                media=f"media/{source.name}",
                sha256=checksum,
                size=total,
                source_language=request.source_language,
                target_language=request.target_language,
            )
            if existing_item is not None:
                item_dir = self.root / existing_item.directory
                destination = item_dir / track.media
                if destination.exists():
                    raise ValueError(f"A different Track already uses filename {source.name!r}")
                partial.replace(destination)
                existing_item.tracks.append(track)
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
            partial.replace(incoming / "media" / source.name)
            self._write_item(incoming, item)
            item_dir.parent.mkdir(parents=True, exist_ok=True)
            incoming.replace(item_dir)
            self._index_item(item, item_dir / "metadata.json")
            return ImportResult(item.item_id, track.track_id, True)
        except Exception:
            # Keep interrupted imports inspectable; retry starts with a new import id.
            raise

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
            if not request.author or not request.author.strip():
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
            author = _safe_name(request.author or "unknown", "unknown")
            title = _safe_name(request.title)
            directory = f"streams/{author}/{title}-{item_id[:6]}"
        return LibraryItem(
            schema_version=ITEM_SCHEMA_VERSION,
            item_id=item_id,
            kind=request.kind,
            title=request.title.strip(),
            rj_code=rj_code,
            author=request.author.strip() if request.author else None,
            created_at=now,
            updated_at=now,
            tracks=[track],
            directory=directory,
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
        return LibraryItem(
            schema_version=int(data["schema_version"]),
            item_id=str(data["item_id"]),
            kind=ItemKind(data["kind"]),
            title=str(data["title"]),
            rj_code=data.get("rj_code"),
            author=data.get("author"),
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
