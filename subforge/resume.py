from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from subforge.config import Config
from subforge.models import Job, SubtitleEntry
from subforge.translate.srt_io import read_srt

SCHEMA_VERSION = 1

logger = logging.getLogger(__name__)


def read_reusable_srt(path: Path) -> list[SubtitleEntry] | None:
    """Read an existing SRT only if it is safe to reuse for resume."""
    try:
        entries = read_srt(path)
    except Exception as exc:
        logger.warning("Cannot reuse SRT %s: %s", path, exc)
        return None

    if not entries:
        logger.warning("Cannot reuse SRT %s: no subtitle entries", path)
        return None

    previous_end = 0.0
    for entry in entries:
        if entry.start < 0 or entry.end <= entry.start:
            logger.warning("Cannot reuse SRT %s: invalid timing at entry %s", path, entry.index)
            return None
        if entry.start < previous_end:
            logger.warning("Cannot reuse SRT %s: overlapping timing at entry %s", path, entry.index)
            return None
        previous_end = entry.end

    return entries


class ResumeStateError(Exception):
    """Raised when resume state cannot be used safely."""


@dataclass
class ResumeState:
    schema_version: int
    job_key: str
    media: dict[str, Any]
    config_fingerprint: dict[str, Any]
    paths: dict[str, str]
    asr: dict[str, Any] = field(default_factory=lambda: {"status": "pending"})
    translation: dict[str, Any] = field(
        default_factory=lambda: {
            "status": "pending",
            "total_batches": 0,
            "completed_batches": {},
        }
    )
    updated_at: str = ""


class ResumeStore:
    """Manage per-media resume state under a jobs directory."""

    def __init__(
        self,
        jobs_dir: Path,
        *,
        identity: str | None = None,
        relative_to: Path | None = None,
    ) -> None:
        self.jobs_dir = jobs_dir
        self.identity = identity
        self.relative_to = relative_to.resolve() if relative_to else None
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    def build_job_key(self, job: Job, config: Config) -> str:
        """Build a stable key for a media file and language pair."""
        payload = "|".join(str(v) for v in self._fingerprint_parts(job, config))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def state_path(self, job: Job, config: Config) -> Path:
        return self.jobs_dir / f"{self.build_job_key(job, config)}.json"

    def create(
        self,
        job: Job,
        config: Config,
        source_srt: Path,
        target_srt: Path,
    ) -> ResumeState:
        return ResumeState(
            schema_version=SCHEMA_VERSION,
            job_key=self.build_job_key(job, config),
            media=self._media_fingerprint(job.file_path),
            config_fingerprint=self._config_fingerprint(job, config),
            paths={
                "source_srt": self._stored_path(source_srt),
                "target_srt": self._stored_path(target_srt),
            },
            updated_at=self._now(),
        )

    def load(self, job: Job, config: Config) -> ResumeState | None:
        path = self.state_path(job, config)
        if not path.exists():
            return None

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            state = self._state_from_dict(data)
        except Exception as exc:
            logger.warning("Ignoring unusable resume state %s: %s", path, exc)
            return None

        if not self._matches(state, job, config):
            logger.info("Ignoring resume state %s: fingerprint mismatch", path)
            return None

        return state

    def save(self, state: ResumeState) -> None:
        path = self.jobs_dir / f"{state.job_key}.json"
        tmp_path = path.with_name(f"{path.name}.tmp")
        state.updated_at = self._now()
        tmp_path.write_text(
            json.dumps(self._state_to_dict(state), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(path)

    def mark_asr_done(self, state: ResumeState) -> None:
        state.asr["status"] = "done"
        self.save(state)

    def save_batch(
        self,
        state: ResumeState,
        batch_index: int,
        entries: list[SubtitleEntry],
        total_batches: int,
    ) -> None:
        state.translation["status"] = "partial"
        state.translation["total_batches"] = total_batches
        completed = state.translation.setdefault("completed_batches", {})
        completed[str(batch_index)] = [
            {
                "index": entry.index,
                "start": entry.start,
                "end": entry.end,
                "text": entry.text,
            }
            for entry in entries
        ]
        self.save(state)

    def mark_translation_done(self, state: ResumeState) -> None:
        state.translation["status"] = "done"
        self.save(state)

    def resolve_path(self, stored_path: str) -> Path:
        path = Path(stored_path)
        if not path.is_absolute() and self.relative_to is not None:
            return self.relative_to / path
        return path

    def _stored_path(self, path: Path) -> str:
        resolved = path.resolve()
        if self.relative_to and (resolved == self.relative_to or self.relative_to in resolved.parents):
            return resolved.relative_to(self.relative_to).as_posix()
        return str(resolved)

    def _fingerprint_parts(self, job: Job, config: Config) -> list[Any]:
        media = self._media_fingerprint(job.file_path)
        cfg = self._config_fingerprint(job, config)
        return [
            self.identity or media["path"],
            media["size"],
            media["mtime_ns"],
            cfg["asr_provider"],
            cfg["source_lang"],
            cfg["target_lang"],
            cfg["asr_model"],
            cfg["deepgram_model"],
            ",".join(cfg["deepgram_keyterms"]),
            cfg["batch_size"],
            cfg["context_size"],
            cfg["llm_model"],
        ]

    def _media_fingerprint(self, file_path: Path) -> dict[str, Any]:
        path = file_path.resolve()
        if self.identity:
            path_value = self.identity
        elif self.relative_to and (path == self.relative_to or self.relative_to in path.parents):
            path_value = path.relative_to(self.relative_to).as_posix()
        else:
            path_value = str(path)
        if not path.exists():
            return {
                "path": path_value,
                "size": 0,
                "mtime_ns": 0,
            }
        stat = path.stat()
        return {
            "path": path_value,
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }

    def _config_fingerprint(self, job: Job, config: Config) -> dict[str, Any]:
        return {
            "asr_provider": config.asr_provider,
            "source_lang": job.source_lang,
            "target_lang": job.target_lang,
            "asr_model": job.model_size,
            "deepgram_model": config.deepgram_model,
            "deepgram_keyterms": sorted(config.deepgram_keyterms),
            "batch_size": config.batch_size,
            "context_size": config.context_size,
            "llm_model": config.llm_model,
        }

    def _matches(self, state: ResumeState, job: Job, config: Config) -> bool:
        if state.schema_version != SCHEMA_VERSION:
            return False
        if state.job_key != self.build_job_key(job, config):
            return False
        if state.media != self._media_fingerprint(job.file_path):
            return False
        return state.config_fingerprint == self._config_fingerprint(job, config)

    def _state_from_dict(self, data: dict[str, Any]) -> ResumeState:
        required = [
            "schema_version",
            "job_key",
            "media",
            "config_fingerprint",
            "paths",
            "asr",
            "translation",
            "updated_at",
        ]
        missing = [key for key in required if key not in data]
        if missing:
            raise ResumeStateError(f"missing field(s): {', '.join(missing)}")

        if not isinstance(data["media"], dict):
            raise ResumeStateError("media must be an object")
        if not isinstance(data["config_fingerprint"], dict):
            raise ResumeStateError("config_fingerprint must be an object")
        if not isinstance(data["paths"], dict):
            raise ResumeStateError("paths must be an object")
        if not isinstance(data["asr"], dict):
            raise ResumeStateError("asr must be an object")
        if not isinstance(data["translation"], dict):
            raise ResumeStateError("translation must be an object")

        return ResumeState(
            schema_version=int(data["schema_version"]),
            job_key=str(data["job_key"]),
            media=data["media"],
            config_fingerprint=data["config_fingerprint"],
            paths={str(k): str(v) for k, v in data["paths"].items()},
            asr=data["asr"],
            translation=data["translation"],
            updated_at=str(data["updated_at"]),
        )

    def _state_to_dict(self, state: ResumeState) -> dict[str, Any]:
        return {
            "schema_version": state.schema_version,
            "job_key": state.job_key,
            "media": state.media,
            "config_fingerprint": state.config_fingerprint,
            "paths": state.paths,
            "asr": state.asr,
            "translation": state.translation,
            "updated_at": state.updated_at,
        }

    def _now(self) -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")
