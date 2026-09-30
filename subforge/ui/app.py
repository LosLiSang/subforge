from __future__ import annotations

import asyncio
import re
import httpx
import hmac
import io
import json
import logging
import math
import mimetypes
import tempfile
import struct
import wave
import secrets
import shutil
import subprocess
import urllib.parse

_system_which = shutil.which
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime
from datetime import timezone
from pathlib import Path
import time
from urllib.parse import parse_qs, urlencode
from uuid import uuid4

from jinja2 import Environment, PackageLoader, select_autoescape
import os
from fastapi import FastAPI, APIRouter
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

FRONTEND_DIST = Path(__file__).resolve().parent / "dist"

from subforge.asr.model_manager import cached_models
from subforge.asr.remote_limiter import RemoteAsrRequestLimiter
from subforge.asr.engine import _audio_duration_seconds
from subforge import __version__
from subforge.config import Config, DEFAULT_MODELS_DIR
from subforge.gemini_audio import (
    GeminiAudioAdapter,
    GoogleGeminiTransport,
    OpenAICompatibleAudioTransport,
    gemini_profile_from_mapping,
)
from subforge.library import CreatorKind, ImportRequest, ImportResult, ItemKind, LibraryStore
from subforge.models import SubtitleEntry
from subforge.presets import ASMR_PRESET
from subforge.segment_processing import (
    SegmentProcessingError,
    SegmentProcessor,
    SegmentRequest,
    WhisperSegmentAdapter,
)
from subforge.subtitle_revision import SubtitleRevisionStore
from subforge.translate.context import translate_all
from subforge.translate.llm_client import translate_batch
from subforge.translate.srt_io import read_srt
from subforge.ui.checks import check_model_configuration, test_profile_connection
from subforge.ui.covers import cover_for_item, covers_dir, replace_cover, get_preset_cover_svg, is_valid_image_bytes, parse_multipart_data
from subforge.ui.model_profiles import ModelProfileStore
from subforge.ui.picker import FilePicker
from subforge.ui.settings import UiSettingsStore
from subforge.ui.tasks import ProcessingSnapshot, TaskManager, WorkerAdapter


@dataclass
class UiDependencies:
    settings: UiSettingsStore
    picker: FilePicker
    profiles: ModelProfileStore
    worker: WorkerAdapter
    startup_token: str
    open_browser: bool = True
    allowed_hosts: set[str] = field(default_factory=lambda: {"127.0.0.1", "localhost"})
    media_concurrency: int = 1
    segment_processor_factory: Callable[[dict], SegmentProcessor] | None = None
    is_fixed_token: bool = False
    no_auth: bool = False


class UiRuntime:
    UPLOAD_MAX_BYTES = 20 * 1024 * 1024  # 20 MB

    def __init__(self, deps: UiDependencies) -> None:
        self.deps = deps
        self.sessions: dict[str, str] = {}
        self.selections: dict[str, Path] = {}
        self.uploaded_selections: set[str] = set()
        self.pending_selections: set[str] = set()
        self.imports: dict[str, dict] = {}  # 后台 URL 下载导入任务状态
        self.download_procs: dict[str, "subprocess.Popen"] = {}  # task_id -> yt-dlp 子进程（用于取消）
        self.segment_candidates: dict[str, dict] = {}  # 已废弃：候选改为任务结果持久化
        self.pending_auto_processing: dict[str, tuple[list[str], ProcessingSnapshot]] = {}
        self.event_loop: asyncio.AbstractEventLoop | None = None
        self.library: LibraryStore | None = None
        self.tasks: TaskManager | None = None
        self.templates = Environment(
            loader=PackageLoader("subforge.ui", "templates"),
            autoescape=select_autoescape(["html", "xml"]),
        )

    async def ensure_auto_processing(self, import_task_id: str) -> None:
        task = self.imports.get(import_task_id)
        pending = self.pending_auto_processing.get(import_task_id)
        if task is None or pending is None:
            return
        if task.get("auto_process_status") in {"scheduling", "queued", "skipped"}:
            return
        track_ids, snapshot = pending
        task["auto_process_status"] = "scheduling"
        try:
            if self.tasks is None:
                raise RuntimeError("字幕任务队列不可用")
            queued = 0
            for track_id in track_ids:
                try:
                    _item, track = self.library.get_track(track_id) if self.library else (None, None)
                except KeyError:
                    continue
                latest = self.tasks.latest_for_track(track_id)
                if track is None or track.status == "playable" or (
                    latest and latest.status in {"queued", "running"}
                ):
                    continue
                await self.tasks.enqueue(track_id, snapshot, mode="from_scratch")
                queued += 1
            self.deps.settings.set_last_processing_snapshot(asdict(snapshot))
            task["auto_process_status"] = "queued" if queued else "skipped"
            task["auto_queued"] = queued
            task["auto_process_message"] = (
                f"已自动加入 {queued} 个字幕处理任务" if queued else "没有需要自动处理的新音轨"
            )
            self.pending_auto_processing.pop(import_task_id, None)
        except Exception as exc:
            task["auto_process_status"] = "pending"
            task["auto_process_message"] = f"等待加入字幕处理队列：{exc}"

    def schedule_auto_processing(
        self,
        import_task_id: str,
        track_ids: list[str],
        snapshot: ProcessingSnapshot,
    ) -> None:
        task = self.imports.get(import_task_id)
        if task is None:
            return
        self.pending_auto_processing[import_task_id] = (track_ids, snapshot)
        task["auto_process_status"] = "pending"
        task["auto_queued"] = 0
        loop = self.event_loop
        if loop is None or loop.is_closed() or not loop.is_running():
            return
        future = asyncio.run_coroutine_threadsafe(
            self.ensure_auto_processing(import_task_id), loop,
        )

        def restore_pending(done) -> None:
            if done.cancelled() or done.exception() is not None:
                current = self.imports.get(import_task_id)
                if current and current.get("auto_process_status") == "scheduling":
                    current["auto_process_status"] = "pending"

        future.add_done_callback(restore_pending)

    def open_active_library(self) -> LibraryStore | None:
        root = self.deps.settings.get_active_library()
        if root is None or not (root / "library.json").is_file():
            return None
        if self.library is None or self.library.root != root.resolve():
            if self.library is not None:
                self.library.close()
            self.library = LibraryStore.open(root)
            self.tasks = TaskManager(
                self.library, self.deps.worker, self.deps.settings.get_asr_concurrency(),
                profile_resolver=self.deps.profiles.resolve,
                deepgram_key_resolver=self.deps.settings.get_deepgram_api_key,
                proxy_resolver=self.deps.settings.get_proxy_url,
                models_dir_resolver=self.deps.settings.get_models_dir,
                direct_model_resolver=self.deps.settings.get_direct_model_path,
                translate_workers=self.deps.settings.get_translate_workers(),
                translate_workers_resolver=self.deps.settings.get_translate_workers,
                translation_prompt_resolver=self.deps.settings.get_translation_prompt,
                segment_runner=_make_segment_runner(self.deps, self),
                remote_asr_concurrency=self.deps.settings.get_remote_asr_concurrency(),
            )
        return self.library

    async def close(self) -> None:
        if self.tasks is not None:
            await self.tasks.close()
        if self.library is not None:
            self.library.close()

    def render(self, name: str, request: Request, **context) -> HTMLResponse:
        csrf = None
        session_id = request.cookies.get("subforge_session")
        if session_id:
            csrf = self.sessions.get(session_id)
        # 支持 HTMX 无刷新切换或传统 iframe/测试模拟。
        # 注意：HX-History-Restore-Request（历史回退/前进且缓存未命中）必须返回完整外壳以恢复顶层 DOM
        is_history_restore = request.headers.get("hx-history-restore-request") == "true"
        is_htmx = (request.headers.get("hx-request") == "true") and not is_history_restore
        is_frame = not is_history_restore and (is_htmx or (request.headers.get("sec-fetch-dest") == "iframe"))
        html = self.templates.get_template(name).render(
            request=request,
            csrf_token=csrf,
            is_frame=is_frame,
            is_htmx=is_htmx,
            **context,
        )
        response = HTMLResponse(html)
        response.headers["Vary"] = "HX-Request, HX-History-Restore-Request, Sec-Fetch-Dest"
        response.headers["Cache-Control"] = "no-cache, private"
        return response


def _make_segment_runner(deps: UiDependencies, runtime: "UiRuntime"):
    """构造片段重处理的后台运行器，交给 TaskManager 异步执行。"""

    async def run(track_id: str, payload: dict, report) -> dict:
        return await _execute_segment_job(deps, runtime, track_id, payload, report)

    return run


def _resolve_segment_window(library, track_id: str, payload: dict):
    """解析片段重处理的时间窗与相交的现有字幕条目。

    入队前归一化与后台执行共用同一套解析逻辑，保证任务中心显示的
    片段范围与实际处理范围一致。
    """
    document = SubtitleRevisionStore(library).load(track_id)
    raw_start_idx = str(payload.get("start_index", "")).strip()
    raw_end_idx = str(payload.get("end_index", "")).strip()
    has_indices = raw_start_idx.isdigit() and raw_end_idx.isdigit()

    start_time_raw = str(payload.get("start_time") or payload.get("start_seconds") or "").strip()
    end_time_raw = str(payload.get("end_time") or payload.get("end_seconds") or "").strip()
    duration = _audio_duration_seconds(library.track_media_path(track_id))

    if has_indices:
        start_index = int(raw_start_idx)
        end_index = int(raw_end_idx)
        max_entries = max(len(document.source_entries), len(document.target_entries))
        if start_index < 1 or end_index < start_index or (max_entries > 0 and end_index > max_entries):
            raise ValueError("请选择连续且有效的字幕范围")
    elif not (start_time_raw or end_time_raw):
        raise ValueError("请提供有效的字幕范围或起止时间")

    if start_time_raw or end_time_raw:
        try:
            target_start = float(start_time_raw) if start_time_raw else 0.0
            target_end = float(end_time_raw) if end_time_raw else (duration or 0.0)
        except ValueError:
            raise ValueError("片段时间范围格式无效")
        if target_start < 0:
            target_start = 0.0
        if duration and target_end > duration + 0.001:
            target_end = duration
        if not 0 <= target_start < target_end:
            raise ValueError("片段时间范围无效")
        selected_source = [e for e in document.source_entries if e.start < target_end and e.end > target_start]
        selected_target = [e for e in document.target_entries if e.start < target_end and e.end > target_start]
    else:
        if not has_indices or start_index > len(document.source_entries) or not document.source_entries:
            raise ValueError("请选择连续且有效的字幕范围")
        selected_source = document.source_entries[start_index - 1:end_index]
        selected_target = document.target_entries[start_index - 1:end_index]
        target_start = selected_source[0].start
        target_end = selected_source[-1].end
    return document, target_start, target_end, selected_source, selected_target


def _enrich_segment_payload_range(library, track_id: str, payload: dict) -> None:
    """入队前把解析后的时间窗写进 payload（best-effort，失败不阻塞入队）。"""
    try:
        _document, target_start, target_end, _source, _target = _resolve_segment_window(library, track_id, payload)
    except (KeyError, TypeError, ValueError, OSError, SegmentProcessingError):
        return
    payload["target_start"] = round(float(target_start), 3)
    payload["target_end"] = round(float(target_end), 3)


def _format_instant(value: str | None) -> str | None:
    """UTC ISO 时间戳 → 本地时区「月-日 时:分」展示。"""
    if not value:
        return None
    try:
        instant = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return instant.astimezone().strftime("%m-%d %H:%M")


def _profile_label(profiles, profile_id) -> str | None:
    if not profile_id:
        return None
    try:
        profile = profiles.resolve(str(profile_id))
    except KeyError:
        return None
    return f"{profile.name} · {profile.model}"


def _health_file_path(deps) -> Path:
    return deps.profiles.path.parent / "profile-health.json"


def _load_profile_health(deps) -> dict[str, dict]:
    path = _health_file_path(deps)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_one_profile_health(deps, profile_id: str, health: dict) -> None:
    current = _load_profile_health(deps)
    current[profile_id] = health
    path = _health_file_path(deps)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _segment_range_display(library, task) -> str | None:
    """片段任务处理的时间范围文案；旧 payload 回退到按字幕序号解析。"""
    payload = task.payload or {}
    start = payload.get("target_start", payload.get("start_time", payload.get("start_seconds")))
    end = payload.get("target_end", payload.get("end_time", payload.get("end_seconds")))
    if start in (None, "") or end in (None, ""):
        try:
            _document, start, end, _source, _target = _resolve_segment_window(library, task.track_id, payload)
        except Exception:
            return None
    try:
        return f"{float(start):.2f} → {float(end):.2f} 秒"
    except (TypeError, ValueError):
        return None


def _task_display_context(library, deps, task) -> dict:
    """任务中心的行内上下文：片段时间范围、ASR/翻译模型、入队/开始时间。"""
    snapshot = task.config_snapshot or {}
    payload = task.payload or {}
    profiles = deps.profiles
    if task.kind == "segment_reprocess":
        processor_name = str(payload.get("processor") or ("gemini" if payload.get("asr_profile_id") else "whisper"))
        asr_profile = _profile_label(profiles, payload.get("asr_profile_id"))
        if processor_name == "gemini":
            asr_display = asr_profile or "音频模型（配置缺失）"
        else:
            asr_display = f"Whisper {payload.get('whisper_model', 'large-v3')}"
        if str(payload.get("processing_mode", "transcribe_then_translate")) == "bilingual_once":
            translation_display = "音频模型一次生成双语"
        else:
            translation_display = _profile_label(profiles, payload.get("llm_profile_id")) or "翻译配置已删除"
        range_display = _segment_range_display(library, task)
    else:
        provider = str(snapshot.get("asr_provider", "local"))
        asr_profile = _profile_label(profiles, snapshot.get("asr_profile_id"))
        if asr_profile:
            asr_display = asr_profile
        elif provider == "local":
            asr_display = f"本地 Whisper {snapshot.get('whisper_model', 'medium')}"
        elif provider == "deepgram":
            asr_display = "Deepgram"
        else:
            asr_display = provider
        translation_display = _profile_label(profiles, snapshot.get("llm_profile_id")) or "翻译配置已删除"
        range_display = None
    return {
        "range": range_display,
        "asr": asr_display,
        "translation": translation_display,
        "created": _format_instant(task.created_at),
        "started": _format_instant(task.started_at),
    }


async def _execute_segment_job(deps: UiDependencies, runtime, track_id: str, payload: dict, report) -> dict:
    """生成片段候选；返回可持久化的结果 dict，不改动正式字幕。"""
    library = runtime.open_active_library()
    if library is None:
        raise RuntimeError("Library 未配置")

    def value(name: str, default: str = "") -> str:
        return str(payload.get(name, default))

    try:
        document, target_start, target_end, selected_source, selected_target = _resolve_segment_window(library, track_id, payload)
    except SegmentProcessingError as exc:
        raise RuntimeError(str(exc)) from exc

    processor_name = value("processor", "")
    if not processor_name:
        processor_name = "gemini" if payload.get("asr_profile_id") else "whisper"
    processing_mode = value("processing_mode", "transcribe_then_translate")
    duration = max(0.0, target_end - target_start)
    if processor_name == "gemini":
        asr_profile_id = value("asr_profile_id")
        if not asr_profile_id:
            raise ValueError("请选择音频转写模型配置")
        asr_profile = deps.profiles.resolve(asr_profile_id)
        limit = max(10.0, float(asr_profile.max_request_seconds or 60.0))
        estimated_chunks = max(1, math.ceil(duration / limit)) if duration > 0 else 1
    else:
        estimated_chunks = 1

    options = {
        "processor": processor_name,
        "whisper_model": value("whisper_model", "large-v3"),
        "scene": value("scene", "asmr"),
        "llm_profile_id": value("llm_profile_id"),
        "asr_profile_id": value("asr_profile_id"),
        "processing_mode": processing_mode,
    }
    asr_options: dict = {}
    if deps.segment_processor_factory is not None:
        processor = deps.segment_processor_factory(options)
    else:
        translate_segment = None
        if processor_name == "whisper" or processing_mode == "transcribe_then_translate":
            profile_id = options["llm_profile_id"]
            if not profile_id:
                raise ValueError("请选择翻译配置")
            profile = deps.profiles.resolve(profile_id)
            translation_config = Config(
                source_lang=document.source_language,
                target_lang=document.target_language,
                batch_size=20,
                context_size=2,
                translate_workers=1,
                translation_global_workers=deps.settings.get_translate_workers(),
                translation_limiter_dir=library.root / ".subforge" / "translation-slots",
                translation_prompt=deps.settings.get_translation_prompt(),
                llm_api_key=profile.api_key,
                llm_base_url=profile.base_url,
                llm_model=profile.model,
                llm_proxy_url=profile.proxy_url,
                llm_verify_tls=profile.verify_tls,
                llm_ca_bundle=profile.ca_bundle,
            )

            async def translate_segment(entries, _source_language, _target_language):
                report("translation", 0.85, "翻译中…", completed=estimated_chunks, total=estimated_chunks)
                return await translate_all(entries, translation_config, translate_batch)

        if processor_name == "whisper":
            model = options["whisper_model"]
            direct_model = deps.settings.get_direct_model_path(model)
            asr_options = {
                "model_size": str(direct_model) if direct_model else model,
                "models_dir": deps.settings.get_models_dir(),
                "local_files_only": bool(direct_model),
                "device": "auto",
                "compute_type": "auto",
            }
            if options["scene"] == "asmr":
                asr_options.update(ASMR_PRESET)
            processor = WhisperSegmentAdapter(translate_fn=translate_segment)
        elif processor_name == "gemini":
            asr_profile_id = options["asr_profile_id"]
            if not asr_profile_id:
                raise ValueError("请选择音频转写模型配置")
            asr_profile = deps.profiles.resolve(asr_profile_id)
            gemini_profile = gemini_profile_from_mapping(asdict(asr_profile))
            remote_limiter = RemoteAsrRequestLimiter(
                library.root / ".subforge" / "remote-asr-slots",
                deps.settings.get_remote_asr_concurrency(),
            )
            transport = (
                GoogleGeminiTransport(gemini_profile, request_limiter=remote_limiter)
                if gemini_profile.protocol == "google_native"
                else OpenAICompatibleAudioTransport(gemini_profile, request_limiter=remote_limiter)
            )
            def on_gemini_progress(ratio: float, completed: int | None = None, total: int | None = None, message: str | None = None):
                tot = total if total is not None else estimated_chunks
                comp = completed if completed is not None else 0
                msg = message or f"ASR 转写中（分片 {comp}/{tot}）"
                report("asr", 0.05 + 0.85 * max(0.0, min(1.0, ratio)), msg, completed=comp, total=tot)

            processor = GeminiAudioAdapter(
                gemini_profile, transport, translate_fn=translate_segment,
                progress_callback=on_gemini_progress,
                chunk_concurrency=deps.settings.get_remote_asr_concurrency(),
            )
        else:
            raise ValueError("未知片段处理器")

    init_msg = f"ASR 转写中（分片 0/{estimated_chunks}）" if processor_name == "gemini" else "Whisper 转写中（分片 0/1）"
    report("asr", 0.05, init_msg, completed=0, total=estimated_chunks)
    request_model = SegmentRequest(
        media_path=library.track_media_path(track_id),
        target_start=target_start,
        target_end=target_end,
        source_language=document.source_language,
        target_language=document.target_language,
        processing_mode=processing_mode,
        recognition_prompt=value("recognition_prompt"),
        asr_options=asr_options,
    )
    candidate = await processor.process(request_model)
    if not candidate.source_entries or not candidate.target_entries:
        raise ValueError("片段处理没有返回完整双语候选")
    return {
        "processor": candidate.processor,
        "target_start": candidate.target_start,
        "target_end": candidate.target_end,
        "warnings": list(candidate.warnings),
        "source_entries": [{"index": e.index, "start": e.start, "end": e.end, "text": e.text} for e in candidate.source_entries],
        "target_entries": [{"index": e.index, "start": e.start, "end": e.end, "text": e.text} for e in candidate.target_entries],
        "current_source": [{"start": e.start, "end": e.end, "text": e.text} for e in selected_source],
        "current_target": [{"start": e.start, "end": e.end, "text": e.text} for e in selected_target],
    }


def create_app(deps: UiDependencies) -> Starlette:
    runtime = UiRuntime(deps)

    def _should_serve_spa(request: Request) -> bool:
        return (
            (FRONTEND_DIST / "index.html").is_file()
            and "PYTEST_CURRENT_TEST" not in os.environ
            and request.query_params.get("legacy") != "1"
        )

    async def homepage(request: Request) -> Response:
        token = request.query_params.get("token")
        if token is not None:
            if not deps.startup_token or not hmac.compare_digest(token, deps.startup_token):
                return Response("Invalid startup token", status_code=401)
            if not deps.is_fixed_token:
                deps.startup_token = ""
            session_id = secrets.token_urlsafe(32)
            runtime.sessions[session_id] = secrets.token_urlsafe(32)
            response = RedirectResponse("/", status_code=303)
            response.set_cookie(
                "subforge_session",
                session_id,
                httponly=True,
                samesite="strict",
                secure=False,
            )
            return response
        if deps.no_auth:
            session_id = request.cookies.get("subforge_session")
            if not session_id or session_id not in runtime.sessions:
                session_id = secrets.token_urlsafe(32)
                runtime.sessions[session_id] = secrets.token_urlsafe(32)
                response = RedirectResponse("/", status_code=303)
                response.set_cookie(
                    "subforge_session",
                    session_id,
                    httponly=True,
                    samesite="strict",
                    secure=False,
                )
                return response
            if _should_serve_spa(request):
                response = FileResponse(FRONTEND_DIST / "index.html")
            else:
                library = runtime.open_active_library()
                if library is None:
                    response = runtime.render("setup.html", request)
                else:
                    response = runtime.render(
                        "library.html",
                        request,
                        library=library,
                        items=library.list_items(),
                        creators=library.list_creators(),
                        profiles=deps.profiles.list_public(),
                        default_cover_info=deps.settings.get_default_cover_info(),
                        default_cover_file_configured=bool(deps.settings.get_default_cover_file()),
                    )
                return response
        if _session_csrf(request, runtime) is None:
            return Response("Authentication required", status_code=401)
        if _should_serve_spa(request):
            return FileResponse(FRONTEND_DIST / "index.html")
        library = runtime.open_active_library()
        if library is None:
            return runtime.render("setup.html", request)
        selected_creator_ids = request.query_params.getlist("creator")
        if selected_creator_ids:
            try:
                library.touch_creators(selected_creator_ids)
            except ValueError:
                selected_creator_ids = []
        creators = library.list_creators()
        creator_by_id = {creator.creator_id: creator for creator in creators}
        items = library.list_items(selected_creator_ids)
        search_query = request.query_params.get("q", "").strip()
        if search_query:
            needle = search_query.casefold()
            items = [
                item for item in items
                if needle in " ".join([
                    item.title,
                    item.rj_code or "",
                    *(creator_by_id[creator_id].name for creator_id in item.creator_ids if creator_id in creator_by_id),
                ]).casefold()
            ]
        total_items = len(items)
        try:
            requested_page = int(request.query_params.get("page", "1"))
        except ValueError:
            requested_page = 1
        limit_param = request.query_params.get("limit") or request.query_params.get("page_size")
        try:
            page_size = max(1, min(60, int(limit_param))) if limit_param else 10
        except ValueError:
            page_size = 10
        page_count = max(1, (total_items + page_size - 1) // page_size)
        current_page = min(max(1, requested_page), page_count)
        page_start = (current_page - 1) * page_size
        page_items = items[page_start:page_start + page_size]

        def page_url(page_number: int) -> str:
            params: list[tuple[str, str]] = []
            if search_query:
                params.append(("q", search_query))
            params.extend(("creator", creator_id) for creator_id in selected_creator_ids)
            if limit_param:
                params.append(("limit", str(page_size)))
            if page_number > 1:
                params.append(("page", str(page_number)))
            query = urlencode(params)
            return f"/?{query}" if query else "/"

        visible_pages = sorted({
            1, page_count,
            *range(max(1, current_page - 2), min(page_count, current_page + 2) + 1),
        })
        pagination_items: list[dict | None] = []
        previous_number = 0
        for page_number in visible_pages:
            if previous_number and page_number - previous_number > 1:
                pagination_items.append(None)
            pagination_items.append({
                "number": page_number,
                "url": page_url(page_number),
                "current": page_number == current_page,
            })
            previous_number = page_number
        item_size_by_id = await asyncio.to_thread(_item_directory_sizes, library.root, page_items)
        return runtime.render(
            "index.html",
            request,
            items=page_items,
            creators=creators,
            creator_by_id=creator_by_id,
            selected_creator_ids=set(selected_creator_ids),
            profiles=deps.profiles.list_public(),
            item_size_by_id=item_size_by_id,
            search_query=search_query,
            current_page=current_page,
            page_count=page_count,
            page_size=page_size,
            total_items=total_items,
            pagination_items=pagination_items,
            previous_page_url=page_url(current_page - 1) if current_page > 1 else None,
            next_page_url=page_url(current_page + 1) if current_page < page_count else None,
        )

    async def session_info(request: Request) -> Response:
        csrf = _session_csrf(request, runtime)
        if csrf is None:
            return JSONResponse({"error": "authentication required"}, status_code=401)
        active_lib = deps.settings.get_active_library()
        return JSONResponse({
            "csrf_token": csrf,
            "authenticated": True,
            "no_auth": deps.no_auth,
            "active_library": str(active_lib) if active_lib else None,
        })

    async def select_library(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        form = await _read_form(request) if request.headers.get("content-type", "").startswith(("application/x-www-form-urlencoded", "multipart/form-data")) else {}
        selection_id = form.get("selection_id")
        if selection_id and selection_id in runtime.selections:
            selected = runtime.selections.pop(selection_id)
        else:
            # tkinter 对话框必须在主线程运行（Tcl 非线程安全）
            selected = deps.picker.choose_directory()
        if selected is None:
            if request.headers.get("accept", "").startswith("application/json"):
                return JSONResponse({"cancelled": True})
            return RedirectResponse("/", status_code=303)
        if runtime.tasks is not None:
            await runtime.tasks.close()
        if runtime.library is not None:
            runtime.library.close()
        runtime.library = LibraryStore.initialize(selected)
        runtime.tasks = TaskManager(
            runtime.library, deps.worker, deps.settings.get_asr_concurrency(),
            profile_resolver=deps.profiles.resolve,
            deepgram_key_resolver=deps.settings.get_deepgram_api_key,
            proxy_resolver=deps.settings.get_proxy_url,
            models_dir_resolver=deps.settings.get_models_dir,
            direct_model_resolver=deps.settings.get_direct_model_path,
            translate_workers=deps.settings.get_translate_workers(),
            translate_workers_resolver=deps.settings.get_translate_workers,
            translation_prompt_resolver=deps.settings.get_translation_prompt,
            segment_runner=_make_segment_runner(deps, runtime),
            remote_asr_concurrency=deps.settings.get_remote_asr_concurrency(),
        )
        deps.settings.set_active_library(selected)
        if request.headers.get("accept", "").startswith("application/json"):
            return JSONResponse({"ok": True, "active_library": str(selected)})
        return RedirectResponse("/", status_code=303)

    async def choose_directory(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        # tkinter 对话框必须在主线程运行（Tcl 非线程安全）
        try:
            selected = deps.picker.choose_directory()
        except Exception as exc:
            return JSONResponse({"error": f"打开目录选择器失败: {exc}"}, status_code=500)
        if selected is None:
            return JSONResponse({"cancelled": True})
        selection_id = uuid4().hex
        runtime.selections[selection_id] = selected.resolve()
        return JSONResponse({"selection_id": selection_id, "name": selected.name})

    async def choose_audio(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        # tkinter 对话框必须在主线程运行（Tcl 非线程安全）
        try:
            selected = deps.picker.choose_audio()
        except Exception as exc:
            return JSONResponse({"error": f"打开文件选择器失败: {exc}"}, status_code=500)
        if selected is None:
            return JSONResponse({"cancelled": True})
        selection_id = uuid4().hex
        runtime.selections[selection_id] = selected.resolve()
        return JSONResponse({"selection_id": selection_id, "filename": selected.name})

    async def choose_media_folder(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        try:
            selected = deps.picker.choose_media_folder()
        except Exception as exc:
            return JSONResponse({"error": f"打开文件夹选择器失败: {exc}"}, status_code=500)
        if selected is None:
            return JSONResponse({"cancelled": True})
        selection_id = uuid4().hex
        runtime.selections[selection_id] = selected.resolve()
        return JSONResponse({"selection_id": selection_id, "name": selected.name})

    async def choose_image(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        try:
            selected = deps.picker.choose_image()
        except Exception as exc:
            return JSONResponse({"error": f"打开图片选择器失败: {exc}"}, status_code=500)
        if selected is None:
            return JSONResponse({"cancelled": True})
        selection_id = uuid4().hex
        runtime.selections[selection_id] = selected.resolve()
        return JSONResponse({"selection_id": selection_id, "filename": selected.name})

    async def upload_image(request: Request) -> Response:
        """接收浏览器直接上传的封面图片，暂存并返回 selection_id。"""
        error = await _authorize_write(request, runtime)
        if error:
            return error
        if request.headers.get("content-length"):
            try:
                declared = int(request.headers["content-length"])
            except ValueError:
                declared = 0
            if declared > UiRuntime.UPLOAD_MAX_BYTES:
                return JSONResponse({"error": "图片文件过大（最大 20 MB）"}, status_code=413)
        content_type = request.headers.get("content-type", "").lower()
        content = b""
        filename = "cover.jpg"
        if "multipart/form-data" in content_type:
            try:
                form = await request.form()
                file = form.get("file") or form.get("image")
                if file and hasattr(file, "read"):
                    content = await file.read()
                    filename = getattr(file, "filename", "cover.jpg") or "cover.jpg"
            except Exception:
                content = b""
        if not content:
            body = await request.body()
            if len(body) > UiRuntime.UPLOAD_MAX_BYTES:
                return JSONResponse({"error": "图片文件过大（最大 20 MB）"}, status_code=413)
            content = body
            raw_name = request.headers.get("x-filename") or request.query_params.get("filename", "cover.jpg")
            filename = urllib.parse.unquote(raw_name)
        if not content:
            return JSONResponse({"error": "上传的文件为空"}, status_code=400)
        suffix = Path(filename).suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
            if "png" in content_type:
                suffix = ".png"
            elif "webp" in content_type:
                suffix = ".webp"
            else:
                suffix = ".jpg"
        tmp_path = Path(tempfile.gettempdir()) / f"subforge_upload_{uuid4().hex}{suffix}"
        tmp_path.write_bytes(content)
        selection_id = uuid4().hex
        runtime.selections[selection_id] = tmp_path
        runtime.uploaded_selections.add(selection_id)
        return JSONResponse({
            "selection_id": selection_id,
            "filename": filename,
            "preview_url": f"/api/selections/{selection_id}/image",
        })

    async def import_item(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        library = runtime.open_active_library()
        if library is None:
            return JSONResponse({"error": "Library is not configured"}, status_code=409)
        values = await _read_form_values(request)
        form = {key: entries[-1] for key, entries in values.items()}
        selection_id = form.get("selection_id", "")
        source = runtime.selections.get(selection_id)
        if source is None:
            return JSONResponse({"error": "Invalid or expired selection"}, status_code=400)
        if selection_id in runtime.pending_selections:
            return JSONResponse({"error": "This selection is already being imported"}, status_code=409)
        runtime.pending_selections.add(selection_id)
        try:
            kind = ItemKind(form.get("kind", ""))
            title = (form.get("title") or "").strip() or source.stem
            result = await asyncio.to_thread(
                library.import_audio,
                ImportRequest(
                    source=source,
                    kind=kind,
                    title=title,
                    rj_code=form.get("rj_code") or None,
                    author=form.get("author") or None,
                    creator_ids=tuple(_creator_ids_from_form(library, values, kind)),
                ),
            )
        except (ValueError, OSError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        finally:
            runtime.pending_selections.discard(selection_id)
        if runtime.selections.get(selection_id) is source:
            runtime.selections.pop(selection_id, None)
            _cleanup_upload_selection(runtime, selection_id, source)
        if form.get("auto_process") == "on" and result.created and runtime.tasks is not None:
            snapshot = _automatic_processing_snapshot(deps)
            if snapshot is not None:
                await runtime.tasks.enqueue(result.track_id, snapshot, mode="from_scratch")
                deps.settings.set_last_processing_snapshot(asdict(snapshot))
        return RedirectResponse(f"/items/{result.item_id}", status_code=303)

    async def import_item_url(request: Request) -> Response:
        """yt-dlp 下载（YouTube/Bilibili）→ 提取音频 → 导入库。

        异步：立即返回 202 + task_id，下载/导入在后台任务执行；
        前端轮询 /api/imports/{task_id} 获取进度，完成后自动刷新。
        同时抓取视频封面写入 .subforge/covers/。
        """
        error = await _authorize_write(request, runtime)
        if error:
            return error
        library = runtime.open_active_library()
        if library is None:
            return JSONResponse({"error": "Library is not configured"}, status_code=409)
        values = await _read_form_values(request)
        form = {key: entries[-1] for key, entries in values.items()}
        url = form.get("url", "").strip()
        if not url:
            return JSONResponse({"error": "url is required"}, status_code=400)
        kind = ItemKind(form.get("kind", "stream_archive"))
        task_id = uuid4().hex
        creator_ids = _creator_ids_from_form(library, values, kind)
        auto_process = form.get("auto_process") == "on"
        auto_snapshot = _automatic_processing_snapshot(deps) if auto_process else None
        runtime.event_loop = asyncio.get_running_loop()
        runtime.imports[task_id] = {
            "task_id": task_id, "kind": "download", "status": "running",
            "stage": "download", "message": "开始下载…", "item_id": None,
            "source_url": url,
            "item_kind": kind.value,
            "rj_code": form.get("rj_code") or None,
            "title": form.get("title") or None,
            "author": form.get("author") or None,
            "creator_ids": list(creator_ids),
            "auto_process": auto_process,
            "auto_process_status": "pending" if auto_snapshot else ("skipped" if auto_process else "disabled"),
            "auto_process_message": (
                "等待导入完成后自动处理" if auto_snapshot
                else ("未配置翻译配置，无法自动处理" if auto_process else "")
            ),
        }
        await _run_url_import(
            runtime, library, url, task_id,
            kind=kind,
            rj_code=form.get("rj_code") or None,
            title=form.get("title") or None,
            author=form.get("author") or None,
            creator_ids=tuple(creator_ids),
            auto_snapshot=auto_snapshot,
        )
        return JSONResponse({"task_id": task_id, "status": "running"}, status_code=202)

    async def video_info(request: Request) -> Response:
        """获取视频 URL 的元数据（标题、创作者/UP主、封面、时长），用于前端导入自动补全。"""
        url = request.query_params.get("url", "").strip()
        if not url and request.method == "POST":
            form = await _read_form(request)
            url = form.get("url", "").strip()
        if not url:
            return JSONResponse({"ok": False, "error": "URL 不能为空"}, status_code=400)
        proxy = deps.settings.get_proxy_url()
        info = await asyncio.to_thread(_fetch_video_info, url, proxy=proxy)
        return JSONResponse(info)

    async def preview_folder_import(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        library = runtime.open_active_library()
        if library is None:
            return JSONResponse({"error": "Library is not configured"}, status_code=409)
        form = await _read_form(request)
        folder = runtime.selections.get(form.get("selection_id", ""))
        if folder is None:
            return JSONResponse({"error": "Invalid or expired selection"}, status_code=400)
        try:
            scan = await asyncio.to_thread(library.scan_rj_folder, folder)
        except (ValueError, OSError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse({
            "folder": folder.name,
            "audio_count": scan.audio_count,
            "video_count": scan.video_count,
            "skipped_count": scan.skipped_count,
            "media_count": len(scan.media),
            "files": [entry.relative_path for entry in scan.media[:20]],
        })

    async def import_folder(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        library = runtime.open_active_library()
        if library is None:
            return JSONResponse({"error": "Library is not configured"}, status_code=409)
        values = await _read_form_values(request)
        form = {key: entries[-1] for key, entries in values.items()}
        folder = runtime.selections.pop(form.get("selection_id", ""), None)
        if folder is None:
            return JSONResponse({"error": "Invalid or expired selection"}, status_code=400)
        rj_code = form.get("rj_code", "").strip()
        if not rj_code:
            match = re.search(r"RJ\d{6,8}", folder.name, re.IGNORECASE)
            if match:
                rj_code = match.group(0).upper()
        if not rj_code:
            return JSONResponse({"error": "RJ code is required"}, status_code=400)
        task_id = uuid4().hex
        auto_process = form.get("auto_process") == "on"
        auto_snapshot = _automatic_processing_snapshot(deps) if auto_process else None
        runtime.event_loop = asyncio.get_running_loop()
        runtime.imports[task_id] = {
            "task_id": task_id, "kind": "media_import", "status": "running",
            "stage": "scan", "message": "扫描目录…", "item_id": None,
            "source_url": folder.name, "progress": 0.0,
            "completed": 0, "total": 0, "imported": 0, "duplicates": 0, "failed": 0,
            "auto_process": auto_process,
            "auto_process_status": "pending" if auto_snapshot else ("skipped" if auto_process else "disabled"),
            "auto_process_message": (
                "等待导入完成后自动处理" if auto_snapshot
                else ("未配置翻译配置，无法自动处理" if auto_process else "")
            ),
        }
        await _run_folder_import(
            runtime, library, folder, task_id,
            rj_code=rj_code, title=form.get("title") or None,
            creator_ids=tuple(_creator_ids_from_form(library, values, ItemKind.RJ_WORK)),
            auto_snapshot=auto_snapshot,
        )
        return JSONResponse({"task_id": task_id, "status": "running"}, status_code=202)

    async def import_status(request: Request) -> Response:
        """查询后台下载导入任务状态（前端轮询）。"""
        task_id = request.path_params["task_id"]
        task = runtime.imports.get(task_id)
        if task is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        if task.get("status") in {"done", "partial"} and task.get("auto_process_status") == "pending":
            runtime.event_loop = asyncio.get_running_loop()
            await runtime.ensure_auto_processing(task_id)
        return JSONResponse(task)

    async def item_detail(request: Request) -> Response:
        if request.headers.get("accept", "").startswith("application/json"):
            return await api_item_detail(request)
        if _should_serve_spa(request):
            return FileResponse(FRONTEND_DIST / "index.html")
        library = runtime.open_active_library()
        if library is None:
            return RedirectResponse("/", status_code=303)
        try:
            item = library.get_item(request.path_params["item_id"])
        except KeyError:
            return Response("Not found", status_code=404)
        task_by_track = {
            track.track_id: runtime.tasks.latest_for_track(track.track_id) if runtime.tasks else None
            for track in item.tracks
        }
        track_media_available = {}
        track_subtitle_available = {}
        track_durations = {}
        for track in item.tracks:
            try:
                track_media_available[track.track_id] = library.track_media_path(track.track_id).is_file()
                track_subtitle_available[track.track_id] = {
                    language: library.track_subtitle_path(track.track_id, language).is_file()
                    for language in (track.source_language, track.target_language)
                }
                track_durations[track.track_id] = _track_duration_label(library, track)
            except (KeyError, ValueError, OSError):
                track_media_available[track.track_id] = False
                track_subtitle_available[track.track_id] = {}
                track_durations[track.track_id] = "--:--"
        model_names = ["medium", "large-v3"]
        models_dir = deps.settings.get_models_dir()
        cached = cached_models(models_dir, model_names)
        direct_models = {
            model for model in model_names
            if deps.settings.get_direct_model_path(model) is not None
        }
        latest_snapshot = next(
            (task.config_snapshot for task in task_by_track.values() if task and task.config_snapshot),
            None,
        )
        public_profiles = deps.profiles.list_public()
        profile_ids = {profile["profile_id"] for profile in public_profiles}
        latest_profile_id = latest_snapshot.get("llm_profile_id") if latest_snapshot else None
        default_profile_id = (
            latest_profile_id if latest_profile_id in profile_ids
            else (public_profiles[0]["profile_id"] if public_profiles else "")
        )
        default_model = (
            latest_snapshot.get("whisper_model") if latest_snapshot
            else next((name for name in ("large-v3", "medium", "base") if name in cached), "medium")
        )
        creators = library.list_creators()
        status_counts: dict[str, int] = {}
        for track in item.tracks:
            status_counts[track.status] = status_counts.get(track.status, 0) + 1
        total_seconds = sum(_track_duration_seconds(library, track) for track in item.tracks)
        snapshot_profile = None
        snapshot_asr_profile = None
        snapshot_merge_profile = None
        if latest_snapshot and latest_snapshot.get("llm_profile_id"):
            snapshot_profile = next(
                (p for p in public_profiles if p["profile_id"] == latest_snapshot["llm_profile_id"]),
                None,
            )
        if latest_snapshot and latest_snapshot.get("asr_profile_id"):
            snapshot_asr_profile = next(
                (p for p in public_profiles if p["profile_id"] == latest_snapshot["asr_profile_id"]),
                None,
            )
        if latest_snapshot and latest_snapshot.get("merge_profile_id"):
            snapshot_merge_profile = next(
                (p for p in public_profiles if p["profile_id"] == latest_snapshot["merge_profile_id"]),
                None,
            )
        actionable_incomplete_tracks = [
            track for track in item.tracks
            if track.status not in ("playable", "completed", "no_speech")
            and not (task_by_track.get(track.track_id) and task_by_track[track.track_id].status in ("queued", "running"))
        ]
        active_tracks = [
            track for track in item.tracks
            if (task_by_track.get(track.track_id) and task_by_track[track.track_id].status in ("queued", "running"))
            or track.status in ("queued", "processing", "running")
        ]
        first_playable_track = next(
            (track for track in item.tracks if track_media_available.get(track.track_id)),
            None,
        )
        overview = {
            "track_count": len(item.tracks),
            "total_duration_label": _format_duration(total_seconds) if total_seconds else "--:--",
            "total_size": sum(track.size for track in item.tracks),
            "status_counts": [(status, status_counts[status]) for status in sorted(status_counts)],
            "playable_count": status_counts.get("playable", 0) + status_counts.get("completed", 0),
            "processing_count": status_counts.get("queued", 0) + status_counts.get("running", 0) + status_counts.get("processing", 0),
            "failed_count": status_counts.get("failed", 0),
            "no_speech_count": status_counts.get("no_speech", 0),
            "actionable_incomplete_count": len(actionable_incomplete_tracks),
            "active_task_count": len(active_tracks),
            "all_completed": (
                (status_counts.get("playable", 0) + status_counts.get("completed", 0) + status_counts.get("no_speech", 0)) == len(item.tracks)
                and len(item.tracks) > 0
            ),
            "first_playable_track_id": first_playable_track.track_id if first_playable_track else None,
        }
        return runtime.render(
            "detail.html", request, item=item, task_by_track=task_by_track,
            profiles=_sort_by_history(public_profiles, library.selection_order("full.translation_profile")),
            models=_sort_names_by_history(model_names, library.selection_order("full.whisper_model")),
            audio_profiles=_sort_by_history(deps.profiles.list_for("transcribe"), library.selection_order("full.asr_profile")),
            merge_profiles=_sort_by_history(deps.profiles.list_for("merge"), library.selection_order("full.merge_profile")),
            cached_models=cached, direct_models=direct_models, default_model=default_model,
            latest_snapshot=latest_snapshot, creators=creators,
            creator_by_id={creator.creator_id: creator for creator in creators},
            track_media_available=track_media_available,
            track_subtitle_available=track_subtitle_available,
            track_durations=track_durations,
            default_profile_id=default_profile_id,
            overview=overview, snapshot_profile=snapshot_profile,
            snapshot_asr_profile=snapshot_asr_profile,
            snapshot_merge_profile=snapshot_merge_profile,
        )

    async def edit_item(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        library = runtime.open_active_library()
        if library is None:
            return Response("Not found", status_code=404)
        values = await _read_form_values(request)
        item_id = request.path_params["item_id"]
        try:
            selection_id = values.get("selection_id", [""])[-1]
            selected = runtime.selections.get(selection_id) if selection_id else None
            if selection_id and selected is None:
                raise ValueError("Invalid or expired cover selection")
            original = library.get_item(item_id)
            kind = ItemKind(values.get("kind", [""])[-1])
            library.update_item(
                item_id,
                title=values.get("title", [""])[-1],
                kind=kind,
                rj_code=values.get("rj_code", [""])[-1] or None,
                creator_ids=_creator_ids_from_form(library, values, kind),
            )
            if selection_id and selected is not None:
                runtime.selections.pop(selection_id, None)
                _cleanup_upload_selection(runtime, selection_id, selected)
                cover_path = covers_dir(library.root) / f"{item_id}.jpg"
                previous_cover = cover_path.read_bytes() if cover_path.exists() else None
                try:
                    replace_cover(library.root, item_id, selected)
                    library.set_cover_source(item_id, "manual_upload")
                except Exception:
                    library.update_item(
                        item_id, title=original.title, kind=original.kind,
                        rj_code=original.rj_code, creator_ids=original.creator_ids,
                    )
                    if previous_cover is None:
                        cover_path.unlink(missing_ok=True)
                    else:
                        cover_path.write_bytes(previous_cover)
                    raise
        except KeyError:
            return Response("Not found", status_code=404)
        except (ValueError, OSError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse({"ok": True, "item_id": item_id})
        return RedirectResponse(f"/items/{item_id}", status_code=303)

    async def stats_page(request: Request) -> Response:
        if _should_serve_spa(request):
            return FileResponse(FRONTEND_DIST / "index.html")
        library = runtime.open_active_library()
        items = library.list_items() if library else []
        tracks = [t for it in items for t in it.tracks]
        status_counts: dict[str, int] = {}
        for t in tracks:
            status_counts[t.status] = status_counts.get(t.status, 0) + 1
        creator_stats = []
        if library:
            for creator in library.list_creators():
                related = [item for item in items if creator.creator_id in item.creator_ids]
                creator_stats.append({
                    "creator": creator,
                    "item_count": len(related),
                    "track_count": sum(len(item.tracks) for item in related),
                    "duration": _creator_duration(library, related),
                })
        stats = {
            "item_count": len(items),
            "track_count": len(tracks),
            "ready_count": sum(1 for t in tracks if t.status == "playable"),
            "rj_count": sum(1 for it in items if it.kind == ItemKind.RJ_WORK),
            "stream_count": sum(1 for it in items if it.kind == ItemKind.STREAM_ARCHIVE),
            "status_counts": sorted(status_counts.items(), key=lambda kv: -kv[1]),
            "creator_stats": creator_stats,
        }
        return runtime.render("stats.html", request, stats=stats)

    async def downloads_page(request: Request) -> Response:
        if _should_serve_spa(request):
            return FileResponse(FRONTEND_DIST / "index.html")
        library = runtime.open_active_library()
        runtime.event_loop = asyncio.get_running_loop()
        for import_task_id, import_task in list(runtime.imports.items()):
            if (
                import_task.get("status") in {"done", "partial"}
                and import_task.get("auto_process_status") == "pending"
            ):
                await runtime.ensure_auto_processing(import_task_id)

        active_tab = request.query_params.get("tab") or "subtitles"
        if active_tab not in {"subtitles", "downloads", "models"}:
            active_tab = "subtitles"

        try:
            requested_page = int(request.query_params.get("page", "1"))
        except ValueError:
            requested_page = 1
        limit_param = request.query_params.get("limit") or request.query_params.get("page_size")
        try:
            page_size = max(1, min(100, int(limit_param))) if limit_param else 10
        except ValueError:
            page_size = 10

        all_processing_tasks = []
        if library is not None and runtime.tasks is not None:
            queued_position = 0
            for task in reversed(runtime.tasks.list_tasks(limit=1000)):
                if task.status == "queued":
                    queued_position += 1
                try:
                    item, track = library.get_track(task.track_id)
                except KeyError:
                    continue
                all_processing_tasks.append({
                    "task": task,
                    "item": item,
                    "track": track,
                    "queue_position": queued_position if task.status == "queued" else None,
                    "context": _task_display_context(library, deps, task),
                })
            all_processing_tasks.reverse()
            worker_summary = runtime.tasks.summary()
        else:
            worker_summary = {
                "local_running": 0, "local_capacity": deps.settings.get_asr_concurrency(),
                "remote_running": 0, "remote_capacity": deps.settings.get_remote_asr_concurrency(),
                "queued": 0,
            }

        all_import_tasks = list(reversed(list(runtime.imports.values())))

        def build_task_pagination(items: list, tab_name: str):
            total = len(items)
            cur_page = requested_page if active_tab == tab_name else 1
            p_count = max(1, (total + page_size - 1) // page_size)
            cur_page = min(max(1, cur_page), p_count)
            start = (cur_page - 1) * page_size
            page_items = items[start : start + page_size]

            def make_page_url(p: int) -> str:
                params: list[tuple[str, str]] = [("tab", tab_name)]
                if limit_param:
                    params.append(("limit", str(page_size)))
                if p > 1:
                    params.append(("page", str(p)))
                query = urlencode(params)
                return f"/downloads?{query}"

            visible = sorted({
                1, p_count,
                *range(max(1, cur_page - 2), min(p_count, cur_page + 2) + 1),
            })
            pag_items: list[dict | None] = []
            prev_n = 0
            for num in visible:
                if prev_n and num - prev_n > 1:
                    pag_items.append(None)
                pag_items.append({
                    "number": num,
                    "url": make_page_url(num),
                    "current": num == cur_page,
                })
                prev_n = num

            return {
                "items": page_items,
                "total": total,
                "current_page": cur_page,
                "page_count": p_count,
                "page_size": page_size,
                "pagination_items": pag_items,
                "previous_page_url": make_page_url(cur_page - 1) if cur_page > 1 else None,
                "next_page_url": make_page_url(cur_page + 1) if cur_page < p_count else None,
            }

        subtitles_pag = build_task_pagination(all_processing_tasks, "subtitles")
        downloads_pag = build_task_pagination(all_import_tasks, "downloads")

        models_dir = deps.settings.get_models_dir()
        model_names = ["tiny", "base", "small", "medium", "large-v3"]
        cached = cached_models(models_dir, model_names)
        direct = {
            name: deps.settings.get_direct_model_path(name)
            for name in model_names
        }
        models = {}
        for name in model_names:
            if direct.get(name):
                models[name] = {"state": "direct", "note": f"直接目录：{direct[name]}"}
            elif name in cached:
                models[name] = {"state": "cached", "note": "已缓存，可离线使用"}
            else:
                models[name] = {"state": "未下载", "note": "首次使用本地 ASR 时自动下载"}
        return runtime.render(
            "downloads.html", request,
            models=models, models_dir=models_dir,
            proxy_url=deps.settings.get_proxy_url(),
            processing_tasks=subtitles_pag["items"],
            subtitles_pagination=subtitles_pag,
            import_tasks=downloads_pag["items"],
            downloads_pagination=downloads_pag,
            worker_summary=worker_summary,
            active_tab=active_tab,
        )

    async def about_page(request: Request) -> Response:
        if _should_serve_spa(request):
            return FileResponse(FRONTEND_DIST / "index.html")
        return runtime.render("about.html", request, version=__version__)

    async def settings_page(request: Request) -> Response:
        if request.method == "GET" and _should_serve_spa(request):
            return FileResponse(FRONTEND_DIST / "index.html")
        if request.method == "POST":
            error = await _authorize_write(request, runtime)
            if error:
                return error
            form = await _read_form(request)
            try:
                if form.get("deepgram_api_key"):
                    deps.settings.set_deepgram_api_key(form["deepgram_api_key"])
                if form.get("default_asr_provider"):
                    deps.settings.set_default_processing_snapshot({
                        "asr_provider": form.get("default_asr_provider", "local"),
                        "scene": form.get("default_scene", "asmr"),
                        "whisper_model": form.get("default_whisper_model", "large-v3"),
                        "llm_profile_id": form.get("default_llm_profile_id", ""),
                        "asr_profile_id": form.get("default_asr_profile_id", ""),
                        "merge_profile_id": form.get("default_merge_profile_id", ""),
                        "asr_chunk_seconds": form.get("default_asr_chunk_seconds", 60),
                    })
                deps.settings.set_asr_concurrency(int(form.get("asr_concurrency", "1")))
                deps.settings.set_remote_asr_concurrency(int(form.get("remote_asr_concurrency", "2")))
                deps.settings.set_translate_workers(int(form.get("translate_workers", "8")))
                deps.settings.set_translation_prompt(form.get("translation_prompt", ""))
                deps.settings.set_proxy_url(form.get("proxy_url", ""))
                models_dir = _resolve_selected_path(runtime, form, "models_dir")
                if models_dir:
                    deps.settings.set_models_dir(models_dir)
                for model in ("medium", "large-v3"):
                    value = _resolve_selected_path(runtime, form, f"direct_{model}")
                    deps.settings.set_direct_model_path(model, value)
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
            if "application/json" in request.headers.get("accept", ""):
                return JSONResponse({"ok": True})
            return RedirectResponse("/settings", status_code=303)
        public_profiles = deps.profiles.list_public()
        translation_profiles = [p for p in public_profiles if "translate" in p.get("capabilities", [])]
        merge_profiles = deps.profiles.list_for("merge")
        return runtime.render(
            "settings.html", request,
            deepgram_key_masked=deps.settings.deepgram_key_display(),
            deepgram_key_configured=bool(deps.settings.get_deepgram_api_key()),
            deepgram_key_deletable=deps.settings.has_stored_deepgram_api_key(),
            asr_concurrency=deps.settings.get_asr_concurrency(),
            remote_asr_concurrency=deps.settings.get_remote_asr_concurrency(),
            translate_workers=deps.settings.get_translate_workers(),
            translation_prompt=deps.settings.get_translation_prompt(),
            proxy_url=deps.settings.get_proxy_url(),
            models_dir=deps.settings.get_models_dir(),
            direct_medium=deps.settings.get_direct_model_path("medium"),
            direct_large_v3=deps.settings.get_direct_model_path("large-v3"),
            audio_profiles=deps.profiles.list_for("transcribe"),
            default_processing=deps.settings.get_default_processing_snapshot() or deps.settings.get_last_processing_snapshot() or {},
            translation_profiles=translation_profiles,
            merge_profiles=merge_profiles,
            models=["large-v3", "medium", "base"],
        )

    async def delete_deepgram_key(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        deps.settings.delete_deepgram_api_key()
        return JSONResponse({"deleted": True})

    async def test_profile(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        try:
            profile = deps.profiles.resolve(request.path_params["profile_id"])
        except KeyError:
            return Response("Not found", status_code=404)
        t0 = time.perf_counter()
        ok, message = await test_profile_connection(profile)
        latency_ms = round((time.perf_counter() - t0) * 1000)
        health_data = {
            "status": "online" if ok else "failed",
            "latency_ms": latency_ms,
            "tested_at": datetime.now(timezone.utc).isoformat(),
            "message": message,
        }
        _save_one_profile_health(deps, profile.profile_id, health_data)
        return JSONResponse({
            "ok": ok,
            "message": message,
            "latency_ms": latency_ms,
            "status": health_data["status"],
            "tested_at": health_data["tested_at"],
        })

    async def check_model(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        model = request.path_params["model"]
        if model not in {"medium", "large-v3"}:
            return Response("Not found", status_code=404)
        ok, message = check_model_configuration(
            model,
            deps.settings.get_models_dir(),
            deps.settings.get_direct_model_path(model),
        )
        return JSONResponse({"ok": ok, "message": message})

    async def delete_profile_key(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        try:
            deps.profiles.delete_key(request.path_params["profile_id"])
        except KeyError:
            return Response("Not found", status_code=404)
        return JSONResponse({"deleted": True})

    async def delete_profile(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        try:
            deps.profiles.delete(request.path_params["profile_id"])
        except KeyError:
            return Response("Not found", status_code=404)
        return JSONResponse({"deleted": True})

    async def create_creator_api(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        library = runtime.open_active_library()
        if library is None:
            return JSONResponse({"error": "Library is not configured"}, status_code=409)
        form = await _read_form(request)
        try:
            creator = library.create_creator(form.get("name", ""), CreatorKind(form.get("kind", "")))
            library.touch_creators([creator.creator_id])
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse({
            "creator_id": creator.creator_id,
            "name": creator.name,
            "kind": creator.kind.value,
        }, status_code=201)

    async def creators_page(request: Request) -> Response:
        if request.method == "GET" and _should_serve_spa(request):
            return FileResponse(FRONTEND_DIST / "index.html")
        library = runtime.open_active_library()
        if library is None:
            return RedirectResponse("/", status_code=303)
        if request.method == "POST":
            error = await _authorize_write(request, runtime)
            if error:
                return error
            form = await _read_form(request)
            action = form.get("action", "")
            try:
                if action == "create":
                    library.create_creator(form.get("name", ""), CreatorKind(form.get("kind", "")))
                elif action == "rename":
                    library.update_creator(form.get("creator_id", ""), name=form.get("name", ""))
                elif action == "merge":
                    library.merge_creators(form.get("source_id", ""), form.get("target_id", ""))
                elif action == "delete":
                    library.delete_creator(form.get("creator_id", ""))
                else:
                    raise ValueError("unsupported creator action")
            except KeyError:
                return Response("Not found", status_code=404)
            except ValueError as exc:
                msg = str(exc)
                if "associated with Library Items" in msg:
                    msg = "该创作者仍有关联作品，无法直接删除。请先在作品中移除该关联。"
                return JSONResponse({"error": msg}, status_code=400)
            if "application/json" in request.headers.get("accept", "").lower():
                return JSONResponse({"ok": True, "action": action})
            return RedirectResponse("/creators", status_code=303)
        creators = library.list_creators()
        items = library.list_items()
        creator_rows = [{
            "creator": creator,
            "item_count": sum(creator.creator_id in item.creator_ids for item in items),
            "track_count": sum(
                len(item.tracks) for item in items if creator.creator_id in item.creator_ids
            ),
        } for creator in creators]
        return runtime.render(
            "creators.html", request, creators=creators, creator_rows=creator_rows,
        )

    async def profiles_page(request: Request) -> Response:
        if request.method == "GET" and _should_serve_spa(request):
            return FileResponse(FRONTEND_DIST / "index.html")
        if request.method == "POST":
            error = await _authorize_write(request, runtime)
            if error:
                return error
            form = await _read_form(request)
            try:
                cap_values = {cap: form.get(f"cap_{cap}") for cap in ("transcribe", "translate", "merge")}
                if any(value is not None for value in cap_values.values()):
                    capabilities = [cap for cap, value in cap_values.items() if value == "on"]
                else:
                    capabilities = ["translate"]  # 旧表单/API 兼容：默认仅翻译
                values = {
                    "name": form.get("name", ""),
                    "base_url": form.get("base_url", ""),
                    "model": form.get("model", ""),
                    "api_key": form.get("api_key", ""),
                    "protocol": form.get("protocol", "openai_compatible"),
                    "capabilities": capabilities,
                    "reasoning_effort": form.get("reasoning_effort", ""),
                    "max_request_seconds": int(form.get("max_request_seconds", "60") or 60),
                    "temperature": float(form.get("temperature", "0") or 0),
                    "transcribe_prompt": form.get("transcribe_prompt", ""),
                    "bilingual_prompt": form.get("bilingual_prompt", ""),
                    "translate_prompt": form.get("translate_prompt", ""),
                    "merge_prompt": form.get("merge_prompt", ""),
                    "proxy_url": form.get("proxy_url", ""),
                    "verify_tls": form.get("verify_tls") == "on",
                    "ca_bundle": form.get("ca_bundle", ""),
                }
                copy_from_profile_id = form.get("copy_from_profile_id", "")
                if copy_from_profile_id:
                    deps.profiles.copy(copy_from_profile_id, **values)
                else:
                    deps.profiles.save(
                        profile_id=form.get("profile_id") or None,
                        **values,
                    )
            except KeyError:
                return Response("Not found", status_code=404)
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
            if "application/json" in request.headers.get("accept", ""):
                return JSONResponse({"ok": True})
            return RedirectResponse("/profiles", status_code=303)
        return runtime.render("profiles.html", request, profiles=deps.profiles.list_public())

    async def save_audio_model(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        form = await _read_form(request)
        try:
            deps.profiles.save(
                profile_id=form.get("profile_id") or None,
                name=form.get("name", ""),
                protocol=form.get("protocol", "google_native"),
                base_url=form.get("base_url", ""),
                model=form.get("model", ""),
                api_key=form.get("api_key", ""),
                capabilities=["transcribe", "translate"],
                max_request_seconds=int(form.get("max_segment_seconds", "60")),
                temperature=float(form.get("temperature", "0") or 0),
                bilingual_prompt=form.get("bilingual_prompt", ""),
                transcribe_prompt=form.get("transcribe_prompt", ""),
                proxy_url=form.get("proxy_url", ""),
                verify_tls=form.get("verify_tls") == "on",
                ca_bundle=form.get("ca_bundle", ""),
            )
        except (TypeError, ValueError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return RedirectResponse("/settings", status_code=303)

    async def delete_audio_model(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        try:
            deps.profiles.delete(request.path_params["profile_id"])
        except KeyError:
            return Response("Not found", status_code=404)
        return RedirectResponse("/audio-models", status_code=303)

    async def delete_audio_model_key(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        try:
            deps.profiles.delete_key(request.path_params["profile_id"])
        except KeyError:
            return Response("Not found", status_code=404)
        return RedirectResponse("/audio-models", status_code=303)

    async def test_audio_model(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        t0 = time.perf_counter()
        try:
            profile = deps.profiles.resolve(request.path_params["profile_id"])
            gemini_profile = gemini_profile_from_mapping(asdict(profile))
            transport = (
                GoogleGeminiTransport(gemini_profile)
                if gemini_profile.protocol == "google_native"
                else OpenAICompatibleAudioTransport(gemini_profile)
            )
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16000)
                frames = b"".join(
                    struct.pack("<h", int(3000 * math.sin(2 * math.pi * 440 * sample / 16000)))
                    for sample in range(4000)
                )
                audio.writeframes(frames)
            result = await transport.generate(
                buffer.getvalue(), "audio/wav",
                "确认你已收到音频输入。只回复 AUDIO_OK，不要解释。",
            )
            if not result.strip():
                raise ValueError("模型返回空内容")
            latency_ms = round((time.perf_counter() - t0) * 1000)
            health_data = {
                "status": "online",
                "latency_ms": latency_ms,
                "tested_at": datetime.now(timezone.utc).isoformat(),
                "message": f"音频输入成功 · {profile.model}",
            }
            _save_one_profile_health(deps, profile.profile_id, health_data)
            return JSONResponse({
                "ok": True,
                "message": health_data["message"],
                "latency_ms": latency_ms,
                "status": "online",
                "tested_at": health_data["tested_at"],
            })
        except KeyError:
            return Response("Not found", status_code=404)
        except (ValueError, RuntimeError, Exception) as exc:
            latency_ms = round((time.perf_counter() - t0) * 1000)
            health_data = {
                "status": "failed",
                "latency_ms": latency_ms,
                "tested_at": datetime.now(timezone.utc).isoformat(),
                "message": str(exc),
            }
            _save_one_profile_health(deps, request.path_params["profile_id"], health_data)
            return JSONResponse({
                "ok": False,
                "message": str(exc),
                "latency_ms": latency_ms,
                "status": "failed",
                "tested_at": health_data["tested_at"],
            }, status_code=400)

    async def process_item(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        library = runtime.open_active_library()
        if library is None or runtime.tasks is None:
            return JSONResponse({"error": "Library is not configured"}, status_code=409)
        try:
            item = library.get_item(request.path_params["item_id"])
        except KeyError:
            return Response("Not found", status_code=404)
        form = await _read_form(request)
        try:
            selected_snapshot = _snapshot_from_form(deps, form)
            deps.settings.set_last_processing_snapshot(asdict(selected_snapshot))
            _record_full_process_selection(library, selected_snapshot)
            scope = form.get("scope", "incomplete")
            mode = form.get("mode", "continue")
            enqueued_count = 0
            for track in item.tracks:
                latest = runtime.tasks.latest_for_track(track.track_id)
                if latest and latest.status in {"queued", "running"}:
                    continue
                if scope == "incomplete" and track.status == "playable":
                    continue
                if track.status == "playable" and mode == "continue":
                    continue
                snapshot = selected_snapshot
                if mode == "continue" and latest and latest.config_snapshot and not form.get("asr_profile_id") and not form.get("llm_profile_id"):
                    snapshot = ProcessingSnapshot(**latest.config_snapshot)
                    deps.profiles.resolve(snapshot.llm_profile_id)
                await runtime.tasks.enqueue(track.track_id, snapshot, mode=mode)
                enqueued_count += 1
        except KeyError:
            return JSONResponse({"error": "LLM profile not found"}, status_code=404)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse({"ok": True, "item_id": item.item_id, "enqueued_count": enqueued_count})
        return RedirectResponse(f"/items/{item.item_id}", status_code=303)

    async def rename_track(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        library = runtime.open_active_library()
        if library is None:
            return Response("Not found", status_code=404)
        track_id = request.path_params["track_id"]
        if runtime.tasks is not None:
            latest = runtime.tasks.latest_for_track(track_id)
            if latest and latest.status in {"queued", "running"}:
                return JSONResponse({"error": "Cannot rename a Track while its task is active"}, status_code=409)
        form = await _read_form(request)
        try:
            item, _track = library.get_track(track_id)
            library.rename_track(track_id, form.get("filename", ""))
        except KeyError:
            return Response("Not found", status_code=404)
        except (ValueError, OSError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return RedirectResponse(f"/items/{item.item_id}", status_code=303)

    async def delete_track(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        library = runtime.open_active_library()
        if library is None:
            return Response("Not found", status_code=404)
        track_id = request.path_params["track_id"]
        try:
            item, _track = library.get_track(track_id)
            if runtime.tasks is not None:
                latest = runtime.tasks.latest_for_track(track_id)
                if latest and latest.status in {"queued", "running"}:
                    await runtime.tasks.cancel(latest.task_id)
            library.trash_track(track_id)
        except KeyError:
            return Response("Not found", status_code=404)
        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse({"ok": True, "track_id": track_id})
        return RedirectResponse(f"/items/{item.item_id}", status_code=303)

    async def start_task(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        library = runtime.open_active_library()
        if library is None or runtime.tasks is None:
            return JSONResponse({"error": "Library is not configured"}, status_code=409)
        form = await _read_form(request)
        mode = form.get("mode", "")
        if not mode:
            item, track = library.get_track(request.path_params["track_id"])
            mode = "from_scratch" if track.status in ("completed", "playable") else "continue"
        previous = runtime.tasks.latest_for_track(request.path_params["track_id"])
        try:
            if mode == "continue" and previous and previous.config_snapshot and not form.get("asr_profile_id") and not form.get("llm_profile_id"):
                snapshot = ProcessingSnapshot(**previous.config_snapshot)
            else:
                snapshot = _snapshot_from_form(deps, form)
            deps.profiles.resolve(snapshot.llm_profile_id)
            task = await runtime.tasks.enqueue(
                request.path_params["track_id"], snapshot, mode=mode,
            )
            deps.settings.set_last_processing_snapshot(asdict(snapshot))
            _record_full_process_selection(library, snapshot)
        except KeyError:
            return JSONResponse({"error": "Track or LLM profile not found"}, status_code=404)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse({"ok": True, "task_id": task.task_id})
        return RedirectResponse(f"/items/{library.get_track(task.track_id)[0].item_id}", status_code=303)

    async def player_page(request: Request) -> Response:
        if "application/json" in request.headers.get("accept", ""):
            return await api_track_detail(request)
        if _should_serve_spa(request):
            return FileResponse(FRONTEND_DIST / "index.html")
        library = runtime.open_active_library()
        if library is None:
            return Response("Not found", status_code=404)
        try:
            item, track = library.get_track(request.path_params["track_id"])
        except KeyError:
            return Response("Not found", status_code=404)
        next_track_id = None
        try:
            index = next(i for i, candidate in enumerate(item.tracks) if candidate.track_id == track.track_id)
            for candidate in item.tracks[index + 1:]:
                if candidate.status in {"playable", "completed", "no_speech"} and library.track_media_path(candidate.track_id).is_file():
                    next_track_id = candidate.track_id
                    break
        except (StopIteration, KeyError, OSError):
            pass
        return runtime.render("player.html", request, item=item, track=track,
                              next_track_id=next_track_id,
                              llm_profiles=_sort_by_history(deps.profiles.list_for("translate"), library.selection_order("segment.translation_profile")),
                              asr_profiles=_sort_by_history(deps.profiles.list_for("transcribe"), library.selection_order("segment.asr_profile")),
                              embed=request.query_params.get("embed") == "1")

    async def track_media(request: Request) -> Response:
        library = runtime.open_active_library()
        if library is None:
            return Response("Not found", status_code=404)
        try:
            path = library.track_media_path(request.path_params["track_id"])
        except KeyError:
            return Response("Not found", status_code=404)
        return _range_response(path, request.headers.get("range"))

    async def selected_image_preview(request: Request) -> Response:
        selected = runtime.selections.get(request.path_params["selection_id"])
        if selected is None or not selected.is_file() or selected.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            return Response("Not found", status_code=404)
        return FileResponse(selected, media_type=mimetypes.guess_type(selected.name)[0] or "image/jpeg")

    async def replace_item_cover(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        library = runtime.open_active_library()
        if library is None:
            return Response("Not found", status_code=404)
        form = await _read_form(request)
        selected = runtime.selections.pop(form.get("selection_id", ""), None)
        if selected is None:
            return JSONResponse({"error": "Invalid or expired selection"}, status_code=400)
        _cleanup_upload_selection(runtime, form.get("selection_id", ""), selected)
        item_id = request.path_params["item_id"]
        try:
            library.get_item(item_id)
            replace_cover(library.root, item_id, selected)
            library.set_cover_source(item_id, "manual_upload")
        except KeyError:
            return Response("Not found", status_code=404)
        except (ValueError, OSError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse({"ok": True, "item_id": item_id})
        return RedirectResponse(f"/items/{item_id}", status_code=303)

    async def get_default_cover_endpoint(request: Request) -> Response:
        cover_info = deps.settings.get_default_cover_info()
        mode = cover_info.get("mode", "preset")
        if mode == "upload" and cover_info.get("has_custom_file"):
            custom_file = deps.settings.get_default_cover_file()
            if custom_file and custom_file.is_file():
                mt = mimetypes.guess_type(custom_file.name)[0] or "image/jpeg"
                return FileResponse(custom_file, media_type=mt, headers={"Cache-Control": "public, max-age=3600"})
        if mode == "url" and cover_info.get("url"):
            return RedirectResponse(cover_info["url"], status_code=307)
        preset = cover_info.get("preset", "default")
        svg_content = get_preset_cover_svg(preset)
        return Response(svg_content, media_type="image/svg+xml; charset=utf-8", headers={"Cache-Control": "public, max-age=3600"})

    async def api_set_default_cover(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        content_type = request.headers.get("content-type", "")
        file_bytes = b""
        filename = "cover.png"
        mode = "upload"
        preset = "default"
        url = ""
        if "multipart/form-data" in content_type:
            try:
                form = await request.form()
                file = form.get("file")
                if file and hasattr(file, "read"):
                    file_bytes = await file.read()
                    filename = getattr(file, "filename", "cover.png") or "cover.png"
                mode = str(form.get("mode", "upload"))
                preset = str(form.get("preset", "default"))
                url = str(form.get("url", ""))
            except Exception:
                body = await request.body()
                fb, fn, fields = parse_multipart_data(body, content_type)
                if fb:
                    file_bytes = fb
                    filename = fn
                mode = fields.get("mode", mode)
                preset = fields.get("preset", preset)
                url = fields.get("url", url)
        elif "application/json" in content_type:
            try:
                body = await request.json()
            except Exception:
                body = {}
            mode = body.get("mode", "preset")
            preset = body.get("preset", "default")
            url = body.get("url", "")
            data_b64 = body.get("data", "")
            if data_b64:
                import base64
                if "," in data_b64:
                    data_b64 = data_b64.split(",", 1)[1]
                try:
                    file_bytes = base64.b64decode(data_b64)
                    filename = body.get("filename", "cover.png")
                except Exception:
                    file_bytes = b""
        else:
            body = await request.body()
            if body and is_valid_image_bytes(body):
                file_bytes = body
                filename = request.headers.get("x-filename", "cover.png")
                mode = "upload"

        if file_bytes:
            if not is_valid_image_bytes(file_bytes, filename):
                return JSONResponse({"error": "上传的文件不是有效的图片格式 (JPG / PNG / WebP)"}, status_code=400)
            deps.settings.save_default_cover_file(file_bytes, filename)
        elif mode:
            deps.settings.set_default_cover_config(mode=mode, preset=preset, url=url)
        return JSONResponse({"ok": True, "default_cover": deps.settings.get_default_cover_info()})

    async def api_reset_default_cover(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        deps.settings.reset_default_cover()
        return JSONResponse({"ok": True, "default_cover": deps.settings.get_default_cover_info()})

    async def item_cover(request: Request) -> Response:
        """按需提取并返回作品第一音轨的内嵌封面（缓存到 .subforge/covers/）。"""
        library = runtime.open_active_library()
        if library is None:
            return Response("Not found", status_code=404)
        try:
            item = library.get_item(request.path_params["item_id"])
        except KeyError:
            return Response("Not found", status_code=404)
        media_path = None
        if item.tracks:
            try:
                media_path = library.track_media_path(item.tracks[0].track_id)
            except KeyError:
                media_path = None
        cover_path = await asyncio.to_thread(cover_for_item, library.root, item.item_id, media_path)
        if cover_path is not None and item.cover_source is None:
            library.set_cover_source(item.item_id, "embedded")
        if cover_path is None:
            return await get_default_cover_endpoint(request)
        stat = cover_path.stat()
        etag = f'"{int(stat.st_mtime)}-{stat.st_size}"'
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304)
        return FileResponse(
            cover_path,
            media_type="image/jpeg",
            headers={
                "Cache-Control": "public, max-age=3600, must-revalidate",
                "ETag": etag,
            },
        )

    async def download_track_subtitle(request: Request) -> Response:
        library = runtime.open_active_library()
        if library is None:
            return Response("Not found", status_code=404)
        track_id = request.path_params["track_id"]
        language = request.path_params["language"]
        try:
            _, track = library.get_track(track_id)
            if language not in {track.source_language, track.target_language}:
                return Response("Not found", status_code=404)
            path = library.track_subtitle_path(track_id, language)
        except KeyError:
            return Response("Not found", status_code=404)
        if not path.is_file():
            return Response("Not found", status_code=404)
        return FileResponse(path, media_type="application/x-subrip", filename=path.name)

    async def track_subtitles(request: Request) -> Response:
        library = runtime.open_active_library()
        if library is None:
            return Response("Not found", status_code=404)
        track_id = request.path_params["track_id"]
        language = request.path_params["language"]
        try:
            _, track = library.get_track(track_id)
            if language not in {track.source_language, track.target_language}:
                return Response("Not found", status_code=404)
            path = library.track_subtitle_path(track_id, language)
        except KeyError:
            return Response("Not found", status_code=404)
        if not path.exists():
            return JSONResponse({"status": "missing", "entries": []}, status_code=404)
        try:
            entries = read_srt(path)
        except Exception:
            return JSONResponse({"status": "invalid", "entries": []}, status_code=422)
        return JSONResponse([
            {"start": entry.start, "end": entry.end, "text": entry.text}
            for entry in entries
        ])

    async def track_subtitles_both(request: Request) -> Response:
        """双轨字幕合并接口：悬浮歌词等调用方一次取回语言对与双轨内容。"""
        library = runtime.open_active_library()
        if library is None:
            return Response("Not found", status_code=404)
        track_id = request.path_params["track_id"]
        try:
            _, track = library.get_track(track_id)
        except KeyError:
            return Response("Not found", status_code=404)

        def read_lang(language: str) -> list:
            path = library.track_subtitle_path(track_id, language)
            if not path.exists():
                return []
            try:
                entries = read_srt(path)
            except Exception:
                return []
            return [{"start": e.start, "end": e.end, "text": e.text} for e in entries]

        return JSONResponse({
            "source_language": track.source_language,
            "target_language": track.target_language,
            "source": read_lang(track.source_language),
            "target": read_lang(track.target_language),
        })

    async def api_track_detail(request: Request) -> Response:
        """返回单轨详情与所属作品元数据，供前端 PlayerPage / 歌词页就绪播放。"""
        library = runtime.open_active_library()
        if library is None:
            return JSONResponse({"error": "Library not initialized"}, status_code=404)
        track_id = request.path_params["track_id"]
        try:
            item, track = library.get_track(track_id)
        except KeyError:
            return JSONResponse({"error": "Track not found"}, status_code=404)
        try:
            has_media = library.track_media_path(track.track_id).is_file()
        except Exception:
            has_media = False
        try:
            has_source_sub = library.track_subtitle_path(track.track_id, track.source_language).is_file()
            has_target_sub = library.track_subtitle_path(track.track_id, track.target_language).is_file()
        except Exception:
            has_source_sub = False
            has_target_sub = False
        dur_seconds = _track_duration_seconds(library, track)
        dur_label = _track_duration_label(library, track)
        track_payload = {
            "track_id": track.track_id,
            "item_id": item.item_id,
            "title": track.media.split("/")[-1],
            "duration": dur_seconds,
            "duration_label": dur_label,
            "size": track.size,
            "status": track.status,
            "source_language": track.source_language,
            "target_language": track.target_language,
            "has_media": has_media,
            "has_source_sub": has_source_sub,
            "has_target_sub": has_target_sub,
        }
        item_payload = {
            "item_id": item.item_id,
            "title": item.title,
            "original_title": getattr(item, "original_title", None),
            "rj_code": item.rj_code,
            "kind": item.kind.value if hasattr(item.kind, "value") else str(item.kind),
            "tags": _extract_item_tags(item),
            "cover_url": f"/covers/{item.item_id}",
        }
        return JSONResponse({"track": track_payload, "item": item_payload})

    def _revision_payload(document) -> dict:
        def serialize(entries):
            return [{"start": entry.start, "end": entry.end, "text": entry.text} for entry in entries]
        return {
            "source_language": document.source_language,
            "target_language": document.target_language,
            "source": serialize(document.source_entries),
            "target": serialize(document.target_entries),
        }

    async def edit_track_subtitle(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        library = runtime.open_active_library()
        if library is None:
            return Response("Not found", status_code=404)
        track_id = request.path_params["track_id"]
        try:
            form = await _read_form_values(request)
            value = lambda name: form.get(name, [""])[-1]
            index = int(value("index"))
            start = float(value("start"))
            end = float(value("end"))
            store = SubtitleRevisionStore(library)
            document = store.load(track_id)
            if index < 1 or index > max(len(document.source_entries), len(document.target_entries)):
                return JSONResponse({"error": "字幕序号不存在"}, status_code=404)
            # 先修复历史越界字幕（Whisper 结尾幻觉），避免整份提交被脏数据卡死；
            # 本次编辑的起止时间随后覆写，仍按 R1.2 严格校验。
            document = store.heal_overflow(track_id, document)
            source_text = value("source_text").strip()
            target_text = value("target_text").strip()
            if not source_text and not target_text and value("text"):
                lang = value("language")
                if lang == "ja":
                    source_text = value("text").strip()
                    target_text = document.target_entries[index - 1].text if index <= len(document.target_entries) else ""
                else:
                    target_text = value("text").strip()
                    source_text = document.source_entries[index - 1].text if index <= len(document.source_entries) else ""
            if index <= len(document.source_entries):
                entry = document.source_entries[index - 1]
                entry.text, entry.start, entry.end = source_text, start, end
            elif source_text:
                return JSONResponse({"error": "源字幕对应关系不存在"}, status_code=409)
            if index <= len(document.target_entries):
                entry = document.target_entries[index - 1]
                entry.text, entry.start, entry.end = target_text, start, end
            elif target_text:
                return JSONResponse({"error": "翻译字幕对应关系不存在"}, status_code=409)
            document = store.commit(track_id, document.source_entries, document.target_entries)
        except KeyError:
            return Response("Not found", status_code=404)
        except (TypeError, ValueError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(_revision_payload(document))

    async def change_track_subtitle_structure(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        library = runtime.open_active_library()
        if library is None:
            return Response("Not found", status_code=404)
        try:
            form = await _read_form_values(request)
            value = lambda name: form.get(name, [""])[-1]
            action = value("action")
            index = int(value("index"))
            store = SubtitleRevisionStore(library)
            if action == "merge":
                document = store.merge(
                    request.path_params["track_id"], index, index + 1,
                    source_text=value("source_text"), target_text=value("target_text"),
                )
            elif action == "split":
                document = store.split(
                    request.path_params["track_id"], index,
                    split_time=float(value("split_time")),
                    source_texts=(value("source_first"), value("source_second")),
                    target_texts=(value("target_first"), value("target_second")),
                )
            elif action == "delete":
                document = store.delete(request.path_params["track_id"], index)
            else:
                return JSONResponse({"error": "未知字幕结构操作"}, status_code=400)
        except KeyError:
            return Response("Not found", status_code=404)
        except (TypeError, ValueError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(_revision_payload(document))

    async def reprocess_track_segment(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        library = runtime.open_active_library()
        if library is None or runtime.tasks is None:
            return JSONResponse({"error": "Library is not configured"}, status_code=409)
        track_id = request.path_params["track_id"]
        try:
            form = await _read_form_values(request)
            payload = {name: entries[-1] for name, entries in form.items()}
            # 入队前归一化时间窗，任务中心可直接展示本次处理的片段时间范围
            _enrich_segment_payload_range(library, track_id, payload)
            task = await runtime.tasks.enqueue_segment_reprocess(track_id, payload)
            _record_segment_selection(library, payload)
        except KeyError:
            return Response("Not found", status_code=404)
        except (TypeError, ValueError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse({"task_id": task.task_id}, status_code=202)

    def _segment_result_entries(items) -> list[SubtitleEntry]:
        return [
            SubtitleEntry(int(item["index"]), float(item["start"]), float(item["end"]), str(item["text"]))
            for item in (items or [])
        ]

    def _segment_candidate_payload(task) -> dict:
        result = task.result or {}
        return {
            "task_id": task.task_id,
            "status": task.status,
            "processor": result.get("processor", ""),
            "target_start": result.get("target_start"),
            "target_end": result.get("target_end"),
            "warnings": list(result.get("warnings", [])),
            "current": {"source": result.get("current_source", []), "target": result.get("current_target", [])},
            "candidate": {"source": result.get("source_entries", []), "target": result.get("target_entries", [])},
        }

    async def segment_candidate(request: Request) -> Response:
        if runtime.tasks is None:
            return Response("Not found", status_code=404)
        try:
            task = runtime.tasks.get_task(request.path_params["task_id"])
        except KeyError:
            return Response("Not found", status_code=404)
        if task.kind != "segment_reprocess" or task.result is None:
            return JSONResponse({"error": "候选尚未就绪"}, status_code=409)
        return JSONResponse(_segment_candidate_payload(task))

    async def confirm_track_segment(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        library = runtime.open_active_library()
        if library is None or runtime.tasks is None:
            return Response("Not found", status_code=404)
        try:
            task = runtime.tasks.get_task(request.path_params["task_id"])
        except KeyError:
            return Response("Not found", status_code=404)
        if task.kind != "segment_reprocess" or not task.result:
            return JSONResponse({"error": "候选尚未就绪"}, status_code=409)
        if task.status not in {"awaiting_review", "failed"}:
            return JSONResponse({"error": "任务状态不允许确认"}, status_code=409)
        result = task.result
        try:
            document = SubtitleRevisionStore(library).replace_range(
                task.track_id,
                target_start=float(result["target_start"]),
                target_end=float(result["target_end"]),
                source_entries=_segment_result_entries(result.get("source_entries")),
                target_entries=_segment_result_entries(result.get("target_entries")),
            )
        except (KeyError, ValueError, TypeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        await runtime.tasks.mark_reviewed(task.task_id, status="completed", message="候选已接受并替换")
        return JSONResponse(_revision_payload(document))

    async def discard_track_segment(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        if runtime.tasks is None:
            return Response("Not found", status_code=404)
        try:
            task = runtime.tasks.get_task(request.path_params["task_id"])
        except KeyError:
            return Response("Not found", status_code=404)
        if task.kind != "segment_reprocess":
            return Response("Not found", status_code=404)
        await runtime.tasks.mark_reviewed(task.task_id, status="discarded", message="候选已放弃")
        return JSONResponse({"ok": True})

    async def restore_track_subtitles(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        library = runtime.open_active_library()
        if library is None:
            return Response("Not found", status_code=404)
        snapshot = request.path_params["snapshot"]
        if snapshot not in {"previous", "baseline"}:
            return Response("Not found", status_code=404)
        try:
            store = SubtitleRevisionStore(library)
            document = store.restore_previous(request.path_params["track_id"]) if snapshot == "previous" else store.restore_baseline(request.path_params["track_id"])
        except KeyError:
            return Response("Not found", status_code=404)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(_revision_payload(document))

    async def task_statuses(request: Request) -> Response:
        if runtime.tasks is None:
            return JSONResponse([])
        task_ids = request.query_params.getlist("task_id")[:200]
        result = []
        for task_id in task_ids:
            try:
                task = runtime.tasks.get_task(task_id)
            except KeyError:
                continue
            result.append({
                "task_id": task.task_id, "status": task.status, "stage": task.stage,
                "progress": task.progress, "completed": task.completed, "total": task.total,
                "message": task.message,
            })
        return JSONResponse(result)

    async def task_status(request: Request) -> Response:
        if runtime.tasks is None:
            return Response("Not found", status_code=404)
        try:
            task = runtime.tasks.get_task(request.path_params["task_id"])
        except KeyError:
            return Response("Not found", status_code=404)
        return JSONResponse({
            "task_id": task.task_id, "status": task.status, "stage": task.stage,
            "progress": task.progress, "completed": task.completed, "total": task.total,
            "message": task.message,
        })

    async def task_events(request: Request) -> Response:
        if runtime.tasks is None:
            return Response("Not found", status_code=404)
        task_id = request.path_params["task_id"]
        try:
            runtime.tasks.get_task(task_id)
        except KeyError:
            return Response("Not found", status_code=404)

        async def stream():
            try:
                async for event in runtime.tasks.subscribe(task_id):
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                # 客户端断开（页面关闭/跳页）时优雅结束，避免 Proactor 噪音
                return

        return StreamingResponse(stream(), media_type="text/event-stream")

    async def cancel_task(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        if runtime.tasks is None:
            return Response("Not found", status_code=404)
        try:
            await runtime.tasks.cancel(request.path_params["task_id"])
        except KeyError:
            return Response("Not found", status_code=404)
        return RedirectResponse(request.headers.get("referer", "/"), status_code=303)

    async def delete_task(request: Request) -> Response:
        """删除一条终态任务记录（不碰媒体与字幕）。"""
        error = await _authorize_write(request, runtime)
        if error:
            return error
        if runtime.tasks is None:
            return Response("Not found", status_code=404)
        try:
            runtime.tasks.delete_task(request.path_params["task_id"])
        except KeyError:
            return Response("Not found", status_code=404)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=409)
        return RedirectResponse(request.headers.get("referer", "/downloads"), status_code=303)

    async def retry_task(request: Request) -> Response:
        """重试失败的字幕处理任务：复用配置快照，从断点继续排队。"""
        error = await _authorize_write(request, runtime)
        if error:
            return error
        if runtime.tasks is None:
            return Response("Not found", status_code=404)
        try:
            task = runtime.tasks.get_task(request.path_params["task_id"])
        except KeyError:
            return Response("Not found", status_code=404)
        if task.status not in ("failed", "cancelled", "interrupted"):
            return JSONResponse({"error": "只有失败、已取消或中断的任务可以重试"}, status_code=409)
        if task.kind == "segment_reprocess":
            # 片段重处理没有配置快照：参数在 payload 里，重试前校验引用的配置仍在
            payload = task.payload or {}
            processor_name = str(payload.get("processor", "whisper"))
            mode = str(payload.get("processing_mode", "transcribe_then_translate"))
            try:
                if processor_name == "gemini":
                    asr_profile_id = str(payload.get("asr_profile_id") or "")
                    if not asr_profile_id:
                        return JSONResponse({"error": "缺少音频转写模型配置，无法重试"}, status_code=400)
                    try:
                        deps.profiles.resolve(asr_profile_id)
                    except KeyError:
                        return JSONResponse({"error": "音频转写模型配置不存在，无法重试"}, status_code=404)
                    if mode != "bilingual_once":
                        llm_profile_id = str(payload.get("llm_profile_id") or "")
                        if not llm_profile_id:
                            return JSONResponse({"error": "缺少翻译配置，无法重试"}, status_code=400)
                        try:
                            deps.profiles.resolve(llm_profile_id)
                        except KeyError:
                            return JSONResponse({"error": "翻译配置不存在，无法重试"}, status_code=404)
                else:
                    if mode != "bilingual_once":
                        llm_profile_id = str(payload.get("llm_profile_id") or "")
                        if not llm_profile_id:
                            return JSONResponse({"error": "缺少翻译配置，无法重试"}, status_code=400)
                        try:
                            deps.profiles.resolve(llm_profile_id)
                        except KeyError:
                            return JSONResponse({"error": "翻译配置不存在，无法重试"}, status_code=404)
            except KeyError:
                return JSONResponse({"error": "任务引用的模型配置不存在，无法重试"}, status_code=404)
            await runtime.tasks.retry_segment(task)
            return RedirectResponse(request.headers.get("referer", "/downloads"), status_code=303)
        if not task.config_snapshot:
            return JSONResponse({"error": "该任务没有可用的配置快照，无法重试"}, status_code=400)
        try:
            snapshot = ProcessingSnapshot(**task.config_snapshot)
            deps.profiles.resolve(snapshot.llm_profile_id)
        except KeyError:
            return JSONResponse({"error": "LLM 配置不存在，无法重试"}, status_code=404)
        except TypeError:
            return JSONResponse({"error": "任务配置快照损坏，无法重试"}, status_code=400)
        await runtime.tasks.retry(task)
        deps.settings.set_last_processing_snapshot(asdict(snapshot))
        return RedirectResponse(request.headers.get("referer", "/downloads"), status_code=303)

    async def retry_import(request: Request) -> Response:
        """重试报错的 URL 下载导入任务（kind=download 且 status=error）。"""
        error = await _authorize_write(request, runtime)
        if error:
            return error
        library = runtime.open_active_library()
        if library is None:
            return JSONResponse({"error": "Library is not configured"}, status_code=409)
        task = runtime.imports.get(request.path_params["task_id"])
        if task is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        if task.get("kind") != "download" or task.get("status") != "error":
            return JSONResponse({"error": "只有报错的 URL 下载任务可以重试"}, status_code=409)
        url = task.get("source_url", "")
        if not url:
            return JSONResponse({"error": "缺少源 URL，无法重试"}, status_code=400)
        auto_snapshot = _automatic_processing_snapshot(deps) if task.get("auto_process") else None
        task.update(
            status="running", stage="download", message="开始重试下载…", item_id=None,
            auto_process_status=("pending" if auto_snapshot else task.get("auto_process_status", "disabled")),
        )
        await _run_url_import(
            runtime, library, url, task["task_id"],
            kind=ItemKind(task.get("item_kind") or "stream_archive"),
            rj_code=task.get("rj_code"), title=task.get("title"), author=task.get("author"),
            creator_ids=tuple(task.get("creator_ids") or ()),
            auto_snapshot=auto_snapshot,
        )
        return RedirectResponse(request.headers.get("referer", "/downloads"), status_code=303)

    async def cancel_import(request: Request) -> Response:
        """取消正在运行的 URL 下载/导入任务：kill 掉 yt-dlp 子进程并转 cancelled。"""
        error = await _authorize_write(request, runtime)
        if error:
            return error
        task_id = request.path_params["task_id"]
        task = runtime.imports.get(task_id)
        if task is None:
            return Response("Not found", status_code=404)
        if task.get("status") != "running":
            return JSONResponse({"error": "只有运行中的下载任务可以取消"}, status_code=409)
        # 标记取消，避免后台 worker 把状态覆盖回 error
        task.update(status="cancelled", stage="download", message="已取消")
        # kill 正在运行的 yt-dlp 子进程
        proc = runtime.download_procs.get(task_id)
        if proc is not None:
            try:
                proc.terminate()
            except OSError:
                pass
        return RedirectResponse(request.headers.get("referer", "/downloads"), status_code=303)

    async def rescan(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        library = runtime.open_active_library()
        if library is not None:
            library.rebuild_index()
        return RedirectResponse("/", status_code=303)

    async def trash_item(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        library = runtime.open_active_library()
        if library is None:
            return Response("Not found", status_code=404)
        try:
            item = library.get_item(request.path_params["item_id"])
            if runtime.tasks:
                for track in item.tracks:
                    task = runtime.tasks.latest_for_track(track.track_id)
                    if task and task.status in {"queued", "running"}:
                        await runtime.tasks.cancel(task.task_id)
            library.trash_item(item.item_id)
        except KeyError:
            return Response("Not found", status_code=404)
        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse({"ok": True, "item_id": item.item_id})
        return RedirectResponse("/", status_code=303)

    async def api_list_items(request: Request) -> Response:
        library = runtime.open_active_library()
        if library is None:
            return JSONResponse({
                "items": [], "total": 0, "page": 1, "limit": 12, "total_pages": 0,
                "all_tags": [], "all_creators": [],
            })

        selected_creator_ids = request.query_params.getlist("creator") or request.query_params.getlist("creator_id")
        creators = library.list_creators()
        creator_by_id = {creator.creator_id: creator for creator in creators}
        items = library.list_items(selected_creator_ids if selected_creator_ids else None)
        search_query = request.query_params.get("q", "").strip()
        if search_query:
            needle = search_query.casefold()
            items = [
                item for item in items
                if needle in " ".join([
                    item.title,
                    item.rj_code or "",
                    *(creator_by_id[cid].name for cid in item.creator_ids if cid in creator_by_id),
                ]).casefold()
            ]
        tag_filter = request.query_params.get("tag", "").strip()
        if tag_filter:
            items = [item for item in items if tag_filter in _extract_item_tags(item)]
        sort_by = request.query_params.get("sort", "created_desc")
        if sort_by == "created_asc":
            items.sort(key=lambda x: x.created_at or "")
        elif sort_by == "created_desc":
            items.sort(key=lambda x: x.created_at or "", reverse=True)
        elif sort_by == "title_asc":
            items.sort(key=lambda x: x.title.lower())
        elif sort_by == "title_desc":
            items.sort(key=lambda x: x.title.lower(), reverse=True)
        elif sort_by == "duration_desc":
            items.sort(key=lambda x: sum(_track_duration_seconds(library, t) for t in x.tracks), reverse=True)
        elif sort_by == "duration_asc":
            items.sort(key=lambda x: sum(_track_duration_seconds(library, t) for t in x.tracks))

        total_items = len(items)
        try:
            page = max(1, int(request.query_params.get("page", "1")))
        except ValueError:
            page = 1
        limit_param = request.query_params.get("limit") or request.query_params.get("page_size")
        try:
            limit = max(1, min(100, int(limit_param))) if limit_param else 12
        except ValueError:
            limit = 12
        total_pages = max(1, (total_items + limit - 1) // limit) if total_items > 0 else 1
        page = min(page, total_pages)
        page_start = (page - 1) * limit
        page_items = items[page_start:page_start + limit]
        item_size_by_id = await asyncio.to_thread(_item_directory_sizes, library.root, page_items)

        all_items = library.list_items()
        all_tags = sorted({tag for it in all_items for tag in _extract_item_tags(it) if tag})
        creator_item_counts: dict[str, int] = {}
        for it in all_items:
            for cid in it.creator_ids:
                creator_item_counts[cid] = creator_item_counts.get(cid, 0) + 1

        creators_list = [
            {
                "creator_id": c.creator_id,
                "name": c.name,
                "kind": c.kind.value if hasattr(c.kind, "value") else str(c.kind),
                "item_count": creator_item_counts.get(c.creator_id, 0),
            }
            for c in creators
        ]

        items_payload = []
        for it in page_items:
            tot_dur = sum(_track_duration_seconds(library, t) for t in it.tracks)
            has_jp = any(library.track_subtitle_path(t.track_id, t.source_language).is_file() for t in it.tracks)
            has_zh = any(library.track_subtitle_path(t.track_id, t.target_language).is_file() for t in it.tracks)
            sub_status = "bilingual" if (has_jp and has_zh) else ("zh" if has_zh else ("jp" if has_jp else "none"))
            items_payload.append({
                "item_id": it.item_id,
                "title": it.title,
                "original_title": getattr(it, "original_title", None),
                "rj_code": it.rj_code,
                "release_date": getattr(it, "release_date", None),
                "kind": it.kind.value if hasattr(it.kind, "value") else str(it.kind),
                "tags": _extract_item_tags(it),
                "creator_ids": list(it.creator_ids),
                "creators": [
                    {
                        "creator_id": cid,
                        "name": creator_by_id[cid].name,
                        "kind": creator_by_id[cid].kind.value if hasattr(creator_by_id[cid].kind, "value") else str(creator_by_id[cid].kind),
                    }
                    for cid in it.creator_ids if cid in creator_by_id
                ],
                "cover_url": f"/covers/{it.item_id}",
                "cover_source": it.cover_source,
                "track_count": len(it.tracks),
                "total_duration": tot_dur,
                "total_duration_label": _format_duration(tot_dur) if tot_dur else "--:--",
                "total_size": item_size_by_id.get(it.item_id, 0),
                "subtitle_status": sub_status,
                "created_at": it.created_at,
                "updated_at": it.updated_at,
            })

        return JSONResponse({
            "items": items_payload,
            "total": total_items,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "all_tags": all_tags,
            "all_creators": creators_list,
        })

    async def api_item_detail(request: Request) -> Response:
        library = runtime.open_active_library()
        if library is None:
            return JSONResponse({"error": "Library not initialized"}, status_code=404)
        item_id = request.path_params["item_id"]
        try:
            item = library.get_item(item_id)
        except KeyError:
            return JSONResponse({"error": "Item not found"}, status_code=404)

        creators = library.list_creators()
        creator_by_id = {c.creator_id: c for c in creators}
        task_by_track = {
            track.track_id: runtime.tasks.latest_for_track(track.track_id) if runtime.tasks else None
            for track in item.tracks
        }
        tracks_payload = []
        status_counts: dict[str, int] = {}
        total_seconds = 0.0
        total_size = 0
        actionable_incomplete_tracks = []
        first_playable_track_id = None

        for track in item.tracks:
            try:
                has_media = library.track_media_path(track.track_id).is_file()
            except Exception:
                has_media = False
            try:
                has_source_sub = library.track_subtitle_path(track.track_id, track.source_language).is_file()
                has_target_sub = library.track_subtitle_path(track.track_id, track.target_language).is_file()
            except Exception:
                has_source_sub = False
                has_target_sub = False
            dur_seconds = _track_duration_seconds(library, track)
            dur_label = _track_duration_label(library, track)
            total_seconds += dur_seconds
            total_size += track.size
            status_counts[track.status] = status_counts.get(track.status, 0) + 1
            if has_media and first_playable_track_id is None:
                first_playable_track_id = track.track_id
            latest_t = task_by_track.get(track.track_id)
            latest_task_info = None
            if latest_t:
                latest_task_info = {
                    "task_id": latest_t.task_id,
                    "status": latest_t.status,
                    "stage": latest_t.stage,
                    "progress": latest_t.progress,
                    "message": latest_t.message,
                }
            if has_media and not (has_source_sub and has_target_sub):
                if not (latest_t and latest_t.status in ("queued", "running")):
                    actionable_incomplete_tracks.append(track.track_id)
            tracks_payload.append({
                "track_id": track.track_id,
                "item_id": item.item_id,
                "title": track.media.split("/")[-1],
                "duration": dur_seconds,
                "duration_label": dur_label,
                "size": track.size,
                "status": track.status,
                "source_language": track.source_language,
                "target_language": track.target_language,
                "has_media": has_media,
                "has_source_sub": has_source_sub,
                "has_target_sub": has_target_sub,
                "latest_task": latest_task_info,
            })

        cached = cached_models(deps.settings.get_models_dir(), ["medium", "large-v3"])
        item_payload = {
            "item_id": item.item_id,
            "title": item.title,
            "original_title": getattr(item, "original_title", None),
            "rj_code": item.rj_code,
            "release_date": getattr(item, "release_date", None),
            "kind": item.kind.value if hasattr(item.kind, "value") else str(item.kind),
            "tags": _extract_item_tags(item),
            "creator_ids": list(item.creator_ids),
            "creators": [
                {
                    "creator_id": cid,
                    "name": creator_by_id[cid].name,
                    "kind": creator_by_id[cid].kind.value if hasattr(creator_by_id[cid].kind, "value") else str(creator_by_id[cid].kind),
                }
                for cid in item.creator_ids if cid in creator_by_id
            ],
            "cover_url": f"/covers/{item.item_id}",
            "cover_source": item.cover_source,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }
        overview = {
            "track_count": len(item.tracks),
            "total_duration_label": _format_duration(total_seconds) if total_seconds else "--:--",
            "total_size": total_size,
            "playable_count": status_counts.get("playable", 0) + status_counts.get("completed", 0),
            "processing_count": status_counts.get("queued", 0) + status_counts.get("running", 0) + status_counts.get("processing", 0),
            "failed_count": status_counts.get("failed", 0),
            "actionable_incomplete_count": len(actionable_incomplete_tracks),
            "all_completed": (
                (status_counts.get("playable", 0) + status_counts.get("completed", 0) + status_counts.get("no_speech", 0)) == len(item.tracks)
                and len(item.tracks) > 0
            ),
            "first_playable_track_id": first_playable_track_id,
        }
        return JSONResponse({
            "item": item_payload,
            "tracks": tracks_payload,
            "overview": overview,
            "available_profiles": {
                "asr_profiles": deps.profiles.list_for("transcribe"),
                "llm_profiles": deps.profiles.list_public(),
                "cached_models": list(cached),
                "default_model": "medium",
                "default_processing": deps.settings.get_default_processing_snapshot() or deps.settings.get_last_processing_snapshot() or {},
            },
        })

    async def api_downloads_history(request: Request) -> Response:
        library = runtime.open_active_library()
        subtitle_tasks = []
        if library and runtime.tasks:
            for task in runtime.tasks.list_tasks(limit=100):
                track_title = None
                item_title = None
                item_id = None
                try:
                    item, track = library.get_track(task.track_id)
                    item_title = item.title
                    item_id = item.item_id
                    track_title = Path(track.media).name
                except Exception:
                    pass
                ctx = _task_display_context(library, deps, task)
                subtitle_tasks.append({
                    "task_id": task.task_id,
                    "track_id": task.track_id,
                    "kind": task.kind,
                    "status": task.status,
                    "stage": task.stage,
                    "progress": task.progress,
                    "message": task.message,
                    "error": getattr(task, "error", None) or (task.message if task.status == "failed" else None),
                    "created_at": getattr(task, "created_at", None),
                    "updated_at": getattr(task, "finished_at", None) or getattr(task, "started_at", None) or getattr(task, "created_at", None),
                    "track_title": track_title or ctx.get("track_title"),
                    "item_title": item_title or ctx.get("item_title"),
                    "item_id": item_id or ctx.get("item_id"),
                    "profile_label": ctx.get("profile_label") or ctx.get("asr") or ctx.get("translation"),
                    "range": ctx.get("range"),
                    "asr": ctx.get("asr"),
                    "translation": ctx.get("translation"),
                })
        download_tasks = []
        for tid, task in runtime.imports.items():
            download_tasks.append({
                "task_id": tid,
                "url": task.get("url", ""),
                "title": task.get("title", ""),
                "status": task.get("status", "pending"),
                "message": task.get("message", ""),
                "error": task.get("error"),
                "progress": task.get("progress", 0.0),
                "item_id": task.get("item_id"),
                "auto_process_status": task.get("auto_process_status"),
            })
        return JSONResponse({
            "subtitle_tasks": subtitle_tasks,
            "download_tasks": download_tasks,
            "tasks": subtitle_tasks,
            "downloads": download_tasks,
        })

    async def api_tasks(request: Request) -> Response:
        library = runtime.open_active_library()
        subtitle_tasks = []
        if library and runtime.tasks:
            for task in runtime.tasks.list_tasks(limit=100):
                track_title = None
                item_title = None
                item_id = None
                try:
                    item, track = library.get_track(task.track_id)
                    item_title = item.title
                    item_id = item.item_id
                    track_title = Path(track.media).name
                except Exception:
                    pass
                ctx = _task_display_context(library, deps, task)
                subtitle_tasks.append({
                    "task_id": task.task_id,
                    "track_id": task.track_id,
                    "kind": task.kind,
                    "status": task.status,
                    "stage": task.stage,
                    "progress": task.progress,
                    "message": task.message,
                    "error": getattr(task, "error", None) or (task.message if task.status == "failed" else None),
                    "created_at": getattr(task, "created_at", None),
                    "updated_at": getattr(task, "finished_at", None) or getattr(task, "started_at", None) or getattr(task, "created_at", None),
                    "track_title": track_title or ctx.get("track_title"),
                    "item_title": item_title or ctx.get("item_title"),
                    "item_id": item_id or ctx.get("item_id"),
                    "profile_label": ctx.get("profile_label") or ctx.get("asr") or ctx.get("translation"),
                    "range": ctx.get("range"),
                    "asr": ctx.get("asr"),
                    "translation": ctx.get("translation"),
                })
        return JSONResponse({"tasks": subtitle_tasks, "subtitle_tasks": subtitle_tasks})

    async def api_retranscribe_task(request: Request) -> Response:
        """重新转写任务：从头开始重新执行指定音轨的 ASR 语音识别与双语翻译流水线。"""
        error = await _authorize_write(request, runtime)
        if error:
            return error
        if runtime.tasks is None:
            return JSONResponse({"error": "TaskManager not initialized"}, status_code=404)
        task_id = request.path_params.get("task_id")
        try:
            old_task = runtime.tasks.get_task(task_id)
        except KeyError:
            return JSONResponse({"error": "Task not found"}, status_code=404)
        
        library = runtime.open_active_library()
        if library is None:
            return JSONResponse({"error": "Library not configured"}, status_code=409)
        
        track_id = old_task.track_id
        snapshot = None
        if getattr(old_task, "config_snapshot", None):
            snapshot = ProcessingSnapshot(**old_task.config_snapshot)
        else:
            default_snap = deps.settings.get_last_processing_snapshot() or deps.settings.get_default_processing_snapshot()
            if default_snap:
                snapshot = ProcessingSnapshot(**default_snap)
        if snapshot is None:
            return JSONResponse({"error": "缺少转写配置"}, status_code=400)
        
        new_task = await runtime.tasks.enqueue(track_id, snapshot, mode="from_scratch")
        return JSONResponse({"ok": True, "task_id": new_task.task_id, "track_id": track_id})

    async def api_profiles(request: Request) -> Response:
        models_dir = deps.settings.get_models_dir()
        cached = cached_models(models_dir, ["base", "small", "medium", "large-v3"])
        library = runtime.open_active_library()
        usage_map: dict[str, dict] = {}
        if library:
            with library._db_lock, library._db:
                cur = library._db.cursor()
                cur.execute(
                    """SELECT option_key, SUM(selected_count) as total_count, MAX(last_selected_at) as last_used
                       FROM selection_history
                       GROUP BY option_key"""
                )
                for row in cur.fetchall():
                    usage_map[row["option_key"]] = {
                        "selected_count": row["total_count"],
                        "last_used_at": row["last_used"],
                    }

        health_map = _load_profile_health(deps)

        def _enrich(items: list[dict]) -> list[dict]:
            enriched = []
            for item in items:
                it = dict(item)
                pid = it.get("profile_id", "")
                it["health"] = health_map.get(pid, {
                    "status": "untested",
                    "latency_ms": None,
                    "tested_at": None,
                    "message": "尚未检测",
                })
                it["usage"] = usage_map.get(pid, {
                    "selected_count": 0,
                    "last_used_at": None,
                })
                enriched.append(it)
            return enriched

        return JSONResponse({
            "asr_profiles": _enrich(deps.profiles.list_for("transcribe")),
            "llm_profiles": _enrich(deps.profiles.list_public()),
            "cached_models": list(cached),
        })

    async def api_get_settings(request: Request) -> Response:
        active_lib = deps.settings.get_active_library()
        default_processing = deps.settings.get_default_processing_snapshot() or deps.settings.get_last_processing_snapshot() or {}
        return JSONResponse({
            "library_root": str(active_lib) if active_lib else None,
            "proxy_url": deps.settings.get_proxy_url(),
            "asr_concurrency": deps.settings.get_asr_concurrency(),
            "remote_asr_concurrency": deps.settings.get_remote_asr_concurrency(),
            "translate_workers": deps.settings.get_translate_workers(),
            "translation_prompt": deps.settings.get_translation_prompt(),
            "no_auth": deps.no_auth or deps.settings.get_no_auth(),
            "has_deepgram_key": bool(deps.settings.get_deepgram_api_key()),
            "has_fixed_token": deps.is_fixed_token or bool(deps.settings.get_fixed_token()),
            "default_cover": deps.settings.get_default_cover_info(),
            "default_processing": default_processing,
        })

    async def api_stats(request: Request) -> Response:
        library = runtime.open_active_library()
        if library is None:
            return JSONResponse({"error": "Library not initialized"}, status_code=404)
        items = library.list_items()
        creators = library.list_creators()
        total_tracks = sum(len(it.tracks) for it in items)
        total_seconds = sum(_track_duration_seconds(library, t) for it in items for t in it.tracks)
        subtitled_tracks = 0
        for it in items:
            for t in it.tracks:
                if library.track_subtitle_path(t.track_id, t.target_language).is_file():
                    subtitled_tracks += 1
        return JSONResponse({
            "total_items": len(items),
            "total_tracks": total_tracks,
            "total_duration": total_seconds,
            "total_duration_label": _format_duration(total_seconds) if total_seconds else "--:--",
            "total_creators": len(creators),
            "subtitled_tracks": subtitled_tracks,
            "subtitled_percentage": round((subtitled_tracks / total_tracks * 100), 1) if total_tracks > 0 else 0,
        })

    async def api_creators(request: Request) -> Response:
        library = runtime.open_active_library()
        if library is None:
            return JSONResponse([])
        creators = library.list_creators()
        items = library.list_items()
        counts: dict[str, int] = {}
        for it in items:
            for cid in it.creator_ids:
                counts[cid] = counts.get(cid, 0) + 1
        return JSONResponse([
            {
                "creator_id": c.creator_id,
                "name": c.name,
                "kind": c.kind.value if hasattr(c.kind, "value") else str(c.kind),
                "item_count": counts.get(c.creator_id, 0),
            }
            for c in creators
        ])

    routes = [
        Mount("/static", StaticFiles(packages=[("subforge.ui", "static")]), name="static"),
        Route("/api/library/items", api_list_items),
        Route("/api/items", api_list_items),
        Route("/api/items/{item_id}", api_item_detail),
        Route("/api/items/{item_id}/trash", trash_item, methods=["POST"]),
        Route("/api/downloads/history", api_downloads_history),
        Route("/api/profiles", api_profiles),
        Route("/api/settings", api_get_settings),
        Route("/api/stats", api_stats),
        Route("/api/creators/list", api_creators),
        Route("/api/tracks/{track_id}/media", track_media),
        Route("/api/tracks/{track_id}/subtitles", track_subtitles_both),
        Route("/api/tracks/{track_id}", api_track_detail),
        Route("/api/tracks/{track_id}/play", api_track_detail),
        Route("/api/tracks/{track_id}/subtitles/edit", edit_track_subtitle, methods=["POST"]),
        Route("/api/tracks/{track_id}/subtitles/structure", change_track_subtitle_structure, methods=["POST"]),
        Route("/api/tracks/{track_id}/subtitles/restore/{snapshot}", restore_track_subtitles, methods=["POST"]),
        Route("/api/tracks/{track_id}/segments/reprocess", reprocess_track_segment, methods=["POST"]),
        Route("/api/tracks/{track_id}/process", start_task, methods=["POST"]),
        Route("/api/tracks/{track_id}/rename", rename_track, methods=["POST"]),
        Route("/api/tracks/{track_id}/delete", delete_track, methods=["POST"]),
        Route("/", homepage),
        Route("/api/session", session_info),
        Route("/library/select", select_library, methods=["POST"]),
        Route("/library/rescan", rescan, methods=["POST"]),
        Route("/picker/audio", choose_audio, methods=["POST"]),
        Route("/picker/media-folder", choose_media_folder, methods=["POST"]),
        Route("/picker/folder", choose_media_folder, methods=["POST"]),
        Route("/picker/image", choose_image, methods=["POST"]),
        Route("/api/upload-image", upload_image, methods=["POST"]),
        Route("/api/selections/{selection_id}/image", selected_image_preview),
        Route("/picker/directory", choose_directory, methods=["POST"]),
        Route("/items/import", import_item, methods=["POST"]),
        Route("/library/import", import_item, methods=["POST"]),
        Route("/api/library/import", import_item, methods=["POST"]),
        Route("/api/video-info", video_info, methods=["GET", "POST"]),
        Route("/api/url-info", video_info, methods=["GET", "POST"]),
        Route("/items/import-url", import_item_url, methods=["POST"]),
        Route("/library/import-url", import_item_url, methods=["POST"]),
        Route("/api/library/import-url", import_item_url, methods=["POST"]),
        Route("/api/import-folders/preview", preview_folder_import, methods=["POST"]),
        Route("/items/import-folder", import_folder, methods=["POST"]),
        Route("/library/import-folder", import_folder, methods=["POST"]),
        Route("/api/library/import-folder", import_folder, methods=["POST"]),
        Route("/api/imports/{task_id}", import_status),
        Route("/api/imports/{task_id}/cancel", cancel_import, methods=["POST"]),
        Route("/api/creators", create_creator_api, methods=["POST"]),
        Route("/items/{item_id}", item_detail),
        Route("/items/{item_id}/edit", edit_item, methods=["POST"]),
        Route("/api/items/{item_id}/process", process_item, methods=["POST"]),
        Route("/items/{item_id}/process", process_item, methods=["POST"]),
        Route("/items/{item_id}/trash", trash_item, methods=["POST"]),
        Route("/items/{item_id}/cover", replace_item_cover, methods=["POST"]),
        Route("/covers/default", get_default_cover_endpoint),
        Route("/covers/{item_id}", item_cover),
        Route("/api/settings/default-cover", api_set_default_cover, methods=["POST"]),
        Route("/api/settings/default-cover/reset", api_reset_default_cover, methods=["POST"]),
        Route("/settings", settings_page, methods=["GET", "POST"]),
        Route("/settings/deepgram/delete-key", delete_deepgram_key, methods=["POST"]),
        Route("/stats", stats_page),
        Route("/downloads", downloads_page),
        Route("/about", about_page),
        Route("/creators", creators_page, methods=["GET", "POST"]),
        Route("/profiles", profiles_page, methods=["GET", "POST"]),
        Route("/audio-models", save_audio_model, methods=["POST"]),
        Route("/audio-models/{profile_id}/test", test_audio_model, methods=["POST"]),
        Route("/audio-models/{profile_id}/delete", delete_audio_model, methods=["POST"]),
        Route("/audio-models/{profile_id}/delete-key", delete_audio_model_key, methods=["POST"]),
        Route("/profiles/{profile_id}/test", test_profile, methods=["POST"]),
        Route("/profiles/{profile_id}/delete", delete_profile, methods=["POST"]),
        Route("/profiles/{profile_id}/delete-key", delete_profile_key, methods=["POST"]),
        Route("/settings/models/{model}/check", check_model, methods=["POST"]),
        Route("/tracks/{track_id}/process", start_task, methods=["POST"]),
        Route("/tracks/{track_id}/rename", rename_track, methods=["POST"]),
        Route("/tracks/{track_id}/delete", delete_track, methods=["POST"]),
        Route("/tracks/{track_id}/play", player_page),
        Route("/tracks/{track_id}/media", track_media),
        Route("/tracks/{track_id}/subtitles", track_subtitles_both),
        Route("/tracks/{track_id}/subtitles/edit", edit_track_subtitle, methods=["POST"]),
        Route("/tracks/{track_id}/subtitles/structure", change_track_subtitle_structure, methods=["POST"]),
        Route("/tracks/{track_id}/subtitles/restore/{snapshot}", restore_track_subtitles, methods=["POST"]),
        Route("/tracks/{track_id}/segments/reprocess", reprocess_track_segment, methods=["POST"]),
        Route("/tasks/{task_id}/candidate", segment_candidate),
        Route("/tasks/{task_id}/candidate/confirm", confirm_track_segment, methods=["POST"]),
        Route("/tasks/{task_id}/candidate/discard", discard_track_segment, methods=["POST"]),
        Route("/tracks/{track_id}/subtitles/{language}", track_subtitles),
        Route("/tracks/{track_id}/subtitles/{language}/download", download_track_subtitle),
        Route("/api/tasks", api_tasks),
        Route("/api/tasks/{task_id}/retry", retry_task, methods=["POST"]),
        Route("/api/tasks/{task_id}/cancel", cancel_task, methods=["POST"]),
        Route("/api/tasks/{task_id}/delete", delete_task, methods=["POST"]),
        Route("/api/tasks/{task_id}/reprocess", api_retranscribe_task, methods=["POST"]),
        Route("/api/tasks/{task_id}/retranscribe", api_retranscribe_task, methods=["POST"]),
        Route("/api/tasks/{task_id}/candidate", segment_candidate),
        Route("/api/tasks/{task_id}/candidate/confirm", confirm_track_segment, methods=["POST"]),
        Route("/api/tasks/{task_id}/candidate/discard", discard_track_segment, methods=["POST"]),
        Route("/api/tasks/status", task_statuses),
        Route("/tasks/{task_id}", task_status),
        Route("/tasks/{task_id}/events", task_events),
        Route("/tasks/{task_id}/cancel", cancel_task, methods=["POST"]),
        Route("/tasks/{task_id}/retry", retry_task, methods=["POST"]),
        Route("/tasks/{task_id}/delete", delete_task, methods=["POST"]),
        Route("/api/imports/{task_id}/retry", retry_import, methods=["POST"]),
    ]

    async def spa_fallback(request: Request) -> Response:
        if _should_serve_spa(request):
            return FileResponse(FRONTEND_DIST / "index.html")
        return Response("Not found", status_code=404)

    if (FRONTEND_DIST / "index.html").is_file():
        routes.append(Route("/{full_path:path}", spa_fallback))

    if (FRONTEND_DIST / "assets").is_dir():
        routes.insert(0, Mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets"))

    @asynccontextmanager
    async def lifespan(app):
        _quiet_proactor_reset_noise()
        runtime.event_loop = asyncio.get_running_loop()
        yield
        await runtime.close()

    app = FastAPI(title="SubForge", version=__version__, routes=routes, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    async def require_read_session(request: Request, call_next):
        public_path = (
            request.url.path.startswith("/static/")
            or request.url.path.startswith("/assets/")
            or request.url.path.endswith(".svg")
            or request.url.path.endswith(".png")
            or request.url.path.endswith(".ico")
            or request.url.path in {"/docs", "/openapi.json", "/redoc", "/subforge-icon.svg", "/favicon.svg"}
        )
        token_exchange = request.url.path == "/" and request.query_params.get("token") is not None
        no_auth_root = deps.no_auth and request.url.path == "/"
        if not public_path and not token_exchange and not no_auth_root and _session_csrf(request, runtime) is None:
            if deps.no_auth:
                session_id = secrets.token_urlsafe(32)
                runtime.sessions[session_id] = secrets.token_urlsafe(32)
                headers = [(k, v) for k, v in request.scope.get("headers", []) if k.lower() != b"cookie"]
                headers.append((b"cookie", f"subforge_session={session_id}".encode("latin-1")))
                request.scope["headers"] = headers
                if hasattr(request, "_cookies"):
                    delattr(request, "_cookies")
                response = await call_next(request)
                response.set_cookie(
                    "subforge_session",
                    session_id,
                    httponly=True,
                    samesite="strict",
                    secure=False,
                )
                return response
            return Response("Authentication required", status_code=401)
        return await call_next(request)

    app.add_middleware(BaseHTTPMiddleware, dispatch=require_read_session)
    app.state.runtime = runtime
    return app


def _sort_by_history(options: list[dict], order: list[str], key: str = "profile_id") -> list[dict]:
    """按选择历史排序下拉项；未出现的项保持原有确定性顺序（稳定排序）。"""
    rank = {option_key: index for index, option_key in enumerate(order)}
    return sorted(options, key=lambda option: rank.get(str(option.get(key, "")), len(rank)))


def _sort_names_by_history(names: list[str], order: list[str]) -> list[str]:
    rank = {option_key: index for index, option_key in enumerate(order)}
    return sorted(names, key=lambda name: rank.get(str(name), len(rank)))


def _record_full_process_selection(library, snapshot: ProcessingSnapshot) -> None:
    """整轨任务入队成功后记录选择历史。"""
    library.record_selection("full.asr_provider", snapshot.asr_provider)
    library.record_selection("full.scene", snapshot.scene)
    library.record_selection("full.whisper_model", snapshot.whisper_model)
    library.record_selection("full.translation_profile", snapshot.llm_profile_id)
    library.record_selection("full.asr_profile", snapshot.asr_profile_id)
    library.record_selection("full.merge_profile", snapshot.merge_profile_id)


def _record_segment_selection(library, payload: dict) -> None:
    """片段重处理任务入队成功后记录选择历史。"""
    for scope, field in (
        ("segment.processor", "processor"),
        ("segment.processing_mode", "processing_mode"),
        ("segment.whisper_model", "whisper_model"),
        ("segment.scene", "scene"),
        ("segment.asr_profile", "asr_profile_id"),
        ("segment.translation_profile", "llm_profile_id"),
    ):
        library.record_selection(scope, str(payload.get(field, "")))


def _snapshot_from_form(deps: UiDependencies, form: dict) -> ProcessingSnapshot:
    """从处理表单构建快照，并校验所选模型能力。"""
    llm_profile_id = form.get("llm_profile_id", "")
    if not llm_profile_id:
        default_snap = deps.settings.get_default_processing_snapshot() or deps.settings.get_last_processing_snapshot() or {}
        llm_profile_id = str(default_snap.get("llm_profile_id", ""))
    profile = deps.profiles.resolve(llm_profile_id)
    if not profile.supports("translate"):
        raise ValueError("所选翻译配置不支持文本翻译")
    asr_provider = form.get("asr_provider", "")
    if not asr_provider:
        asr_provider = "model" if form.get("asr_profile_id") else "local"
    if asr_provider not in {"local", "deepgram", "model"}:
        raise ValueError("不支持的 ASR 提供商")
    asr_profile_id = ""
    if asr_provider == "model":
        asr_profile_id = form.get("asr_profile_id", "")
        if not asr_profile_id:
            raise ValueError("请选择音频转写模型配置")
        asr_profile = deps.profiles.resolve(asr_profile_id)
        if not asr_profile.supports("transcribe"):
            raise ValueError("所选 ASR 模型不支持音频转写")
    try:
        asr_chunk_seconds = int(form.get("asr_chunk_seconds", "60"))
    except (TypeError, ValueError) as exc:
        raise ValueError("网络 ASR 分片大小必须是整数秒") from exc
    if not 10 <= asr_chunk_seconds <= 3600:
        raise ValueError("网络 ASR 分片大小必须在 10 到 3600 秒之间")
    merge_profile_id = form.get("merge_profile_id", "") if asr_provider == "model" else ""
    if merge_profile_id:
        merge_profile = deps.profiles.resolve(merge_profile_id)
        if not merge_profile.supports("merge"):
            raise ValueError("所选合并模型不支持文本合并")
    return ProcessingSnapshot(
        asr_provider=asr_provider,
        scene=form.get("scene", "normal"),
        whisper_model=form.get("whisper_model", "medium"),
        llm_profile_id=profile.profile_id,
        asr_profile_id=asr_profile_id,
        merge_profile_id=merge_profile_id,
        asr_chunk_seconds=asr_chunk_seconds,
    )


def _automatic_processing_snapshot(deps: UiDependencies) -> ProcessingSnapshot | None:
    profiles = deps.profiles.list_public()
    translation_profiles = [p for p in profiles if "translate" in p.get("capabilities", [])]
    if not translation_profiles:
        return None
    profile_ids = {profile["profile_id"] for profile in translation_profiles}
    saved = deps.settings.get_default_processing_snapshot() or deps.settings.get_last_processing_snapshot() or {}
    profile_id = str(saved.get("llm_profile_id", ""))
    if profile_id not in profile_ids:
        profile_id = translation_profiles[0]["profile_id"]
    asr_provider = str(saved.get("asr_provider", "local"))
    asr_profile_id = str(saved.get("asr_profile_id", ""))
    if asr_provider == "model":
        transcribe_ids = {p["profile_id"] for p in profiles if "transcribe" in p.get("capabilities", [])}
        if asr_profile_id not in transcribe_ids:
            asr_provider, asr_profile_id = "local", ""
    else:
        asr_profile_id = ""
    merge_profile_id = str(saved.get("merge_profile_id", ""))
    try:
        asr_chunk_seconds = int(saved.get("asr_chunk_seconds", 60))
    except (TypeError, ValueError):
        asr_chunk_seconds = 60
    asr_chunk_seconds = min(3600, max(10, asr_chunk_seconds))
    merge_ids = {p["profile_id"] for p in profiles if "merge" in p.get("capabilities", [])}
    if merge_profile_id not in merge_ids:
        merge_profile_id = ""
    scene = str(saved.get("scene", "asmr"))
    whisper_model = str(saved.get("whisper_model", "large-v3"))
    return ProcessingSnapshot(
        asr_provider=asr_provider if asr_provider in {"local", "deepgram", "model"} else "local",
        scene=scene if scene in {"asmr", "normal"} else "asmr",
        whisper_model=whisper_model or "large-v3",
        llm_profile_id=profile_id,
        asr_profile_id=asr_profile_id,
        merge_profile_id=merge_profile_id,
        asr_chunk_seconds=asr_chunk_seconds,
    )


def _session_csrf(request: Request, runtime: UiRuntime) -> str | None:
    session_id = request.cookies.get("subforge_session")
    return runtime.sessions.get(session_id) if session_id else None


def _cleanup_upload_selection(runtime: UiRuntime, selection_id: str, source: Path) -> None:
    """删除 upload_image 创建的临时文件（系统文件选择器选的文件不删）。"""
    if selection_id not in runtime.uploaded_selections:
        return
    runtime.uploaded_selections.discard(selection_id)
    try:
        source.unlink(missing_ok=True)
    except OSError:
        pass


async def _authorize_write(request: Request, runtime: UiRuntime) -> Response | None:
    host = request.headers.get("host", "").split(":", 1)[0].lower()
    if host not in {value.lower() for value in runtime.deps.allowed_hosts}:
        return JSONResponse({"error": "invalid host"}, status_code=403)
    csrf = _session_csrf(request, runtime)
    if csrf is None:
        return JSONResponse({"error": "authentication required"}, status_code=401)
    origin = request.headers.get("origin")
    allowed_origins = {
        f"http://{request.headers.get('host')}",
        f"https://{request.headers.get('host')}",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    }
    if origin and origin not in allowed_origins:
        return JSONResponse({"error": "invalid origin"}, status_code=403)
    supplied = request.headers.get("x-csrf-token")
    if not supplied:
        try:
            body = (await request.body()).decode("utf-8", errors="ignore")
            supplied = parse_qs(body, keep_blank_values=True).get("csrf_token", [""])[-1]
        except Exception:
            supplied = ""
    if not supplied or not hmac.compare_digest(supplied, csrf):
        if runtime.deps.no_auth:
            return None
        return JSONResponse({"error": "invalid csrf token"}, status_code=403)
    return None


def _range_response(path: Path, range_header: str | None) -> Response:
    size = path.stat().st_size
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    headers = {"Accept-Ranges": "bytes"}
    if not range_header:
        headers["Content-Length"] = str(size)
        return StreamingResponse(path.open("rb"), media_type=content_type, headers=headers)
    if not range_header.startswith("bytes=") or "," in range_header:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    value = range_header[6:]
    try:
        start_text, end_text = value.split("-", 1)
        if start_text:
            start = int(start_text)
            end = int(end_text) if end_text else size - 1
        else:
            suffix = int(end_text)
            start = max(0, size - suffix)
            end = size - 1
        if start < 0 or end < start or start >= size:
            raise ValueError
        end = min(end, size - 1)
    except (ValueError, TypeError):
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})

    def chunk():
        try:
            with path.open("rb") as handle:
                handle.seek(start)
                remaining = end - start + 1
                while remaining:
                    data = handle.read(min(64 * 1024, remaining))
                    if not data:
                        break
                    remaining -= len(data)
                    yield data
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            # 客户端强制断开（如播放器 iframe 跳页被销毁）：优雅结束流，
            # 避免 Windows Proactor 在已关闭 socket 上再 shutdown 报
            # ConnectionResetError [WinError 10054]（asyncio 已知问题）。
            return

    headers.update({
        "Content-Range": f"bytes {start}-{end}/{size}",
        "Content-Length": str(end - start + 1),
    })
    return StreamingResponse(chunk(), status_code=206, media_type=content_type, headers=headers)


logger = logging.getLogger(__name__)


def _quiet_proactor_reset_noise() -> None:
    """Silence known asyncio Proactor noise on Windows.

    When a client forcibly closes a connection (e.g. the global player
    iframe is destroyed while streaming audio), ProactorEventLoop's
    _call_connection_lost callback calls shutdown() on an already-closed
    socket and asyncio logs "Exception in callback ... ConnectionResetError:
    [WinError 10054]". The transport is already gone; this is harmless
    noise (python/cpython #38856, #39010). We suppress only those.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    def handler(loop_: asyncio.AbstractEventLoop, context: dict) -> None:
        exc = context.get("exception")
        message = str(context.get("message", ""))
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        if "_call_connection_lost" in message or "_ProactorBasePipeTransport" in message:
            return
        loop_.default_exception_handler(context)

    loop.set_exception_handler(handler)


async def _run_folder_import(
    runtime: "UiRuntime",
    library: LibraryStore,
    folder: Path,
    task_id: str,
    *,
    rj_code: str,
    title: str | None,
    creator_ids: tuple[str, ...],
    auto_snapshot: ProcessingSnapshot | None = None,
) -> None:
    import threading

    def progress(event: dict) -> None:
        task = runtime.imports.get(task_id)
        if not task:
            return
        total = int(event.get("total") or 0)
        completed = int(event.get("completed") or 0)
        stage = str(event.get("stage") or "import")
        labels = {"convert": "转换视频", "import": "导入音频", "complete": "写入 Library"}
        task.update(
            stage=stage,
            message=f"{labels.get(stage, stage)}：{event.get('current', '')}".rstrip("："),
            completed=completed,
            total=total,
            progress=(completed / total) if total else 0.0,
            imported=int(event.get("imported") or 0),
            duplicates=int(event.get("duplicates") or 0),
            failed=int(event.get("failed") or 0),
        )

    def worker() -> None:
        task = runtime.imports.get(task_id)
        try:
            result = library.import_rj_folder(
                folder, rj_code=rj_code, title=title,
                creator_ids=creator_ids, progress_callback=progress,
            )
            if task:
                task.update(
                    status="done" if result.status == "completed" else result.status,
                    stage="complete", item_id=result.item_id, progress=1.0,
                    imported=result.imported_count, duplicates=result.duplicate_count,
                    skipped=result.skipped_count, failed=result.failed_count,
                    failures=result.failures,
                    message=(
                        f"导入 {result.imported_count}，重复 {result.duplicate_count}，"
                        f"跳过 {result.skipped_count}，失败 {result.failed_count}"
                    ),
                )
            if auto_snapshot is not None and result.imported_track_ids:
                runtime.schedule_auto_processing(
                    task_id, list(result.imported_track_ids), auto_snapshot,
                )
            elif auto_snapshot is not None and task:
                task.update(
                    auto_process_status="skipped", auto_queued=0,
                    auto_process_message="没有需要自动处理的新音轨",
                )
        except (ValueError, OSError) as exc:
            if task:
                task.update(status="error", stage="failed", message=str(exc))

    threading.Thread(
        target=worker, daemon=True, name=f"folder-import-{task_id[:8]}"
    ).start()


async def _run_url_import(
    runtime: "UiRuntime",
    library: LibraryStore,
    url: str,
    task_id: str,
    *,
    kind: ItemKind,
    rj_code: str | None,
    title: str | None,
    author: str | None,
    creator_ids: tuple[str, ...],
    auto_snapshot: ProcessingSnapshot | None = None,
) -> None:
    """后台执行 URL 下载+导入。

    用独立线程而非 asyncio 任务：下载/导入是 IO 密集，且线程不依赖
    事件循环存活（TestClient 每请求可能新 loop，任务会被遇弃）。
    """
    import threading

    def _set(status: str, message: str, item_id: str | None = None) -> None:
        task = runtime.imports.get(task_id)
        if task:
            task.update(status=status, message=message, item_id=item_id)

    def _is_cancelled() -> bool:
        task = runtime.imports.get(task_id)
        return bool(task and task.get("status") == "cancelled")

    def _register_proc(proc: "object | None") -> None:
        # 记录当前 yt-dlp 子进程，取消时据此 kill；None 表示已结束
        if proc is None:
            runtime.download_procs.pop(task_id, None)
        else:
            runtime.download_procs[task_id] = proc

    def _worker() -> None:
        try:
            _set("running", "下载中…")
            result = _download_and_import(
                library, url,
                kind=kind, rj_code=rj_code, title=title, author=author,
                creator_ids=creator_ids,
                proxy=runtime.deps.settings.get_proxy_url(),
                proc_cb=_register_proc,
                status_cb=lambda msg: _set("running", msg),
                cancelled=_is_cancelled,
            )
            if _is_cancelled():
                return
            _set("done", "导入完成", result.item_id)
            if auto_snapshot is not None and result.created:
                runtime.schedule_auto_processing(task_id, [result.track_id], auto_snapshot)
            elif auto_snapshot is not None:
                task = runtime.imports.get(task_id)
                if task:
                    task.update(
                        auto_process_status="skipped", auto_queued=0,
                        auto_process_message="媒体已存在，没有新增字幕处理任务",
                    )
        except Exception as exc:  # 含 subprocess.TimeoutExpired：超时也转 error，避免卡 running
            if _is_cancelled():
                return  # 用户已取消，保留 cancelled 状态，不覆盖为 error
            _set("error", str(exc) or exc.__class__.__name__)

    threading.Thread(target=_worker, daemon=True, name=f"url-import-{task_id[:8]}").start()


class _DownloadCancelled(Exception):
    """用户主动取消 URL 下载任务。"""


def _spawn_and_wait(
    cmd: list[str],
    proc_cb: "Callable[[object | None], None]" | None,
    *, timeout: int = 600,
) -> "subprocess.CompletedProcess":
    """用 Popen 运行子进程以便中途 kill（取消），超时时终止进程并抛出。"""
    import subprocess as _sp

    proc = _sp.Popen(
        cmd,
        stdin=_sp.DEVNULL,
        stdout=_sp.PIPE,
        stderr=_sp.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc_cb:
        proc_cb(proc)
    try:
        out, err = proc.communicate(timeout=timeout)
    except _sp.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        raise
    finally:
        if proc_cb:
            proc_cb(None)
    return _sp.CompletedProcess(cmd, proc.returncode, out, err)


def _is_bilibili_url(url: str) -> bool:
    low = url.lower()
    return "bilibili.com" in low or "b23.tv" in low


def _fetch_video_info(url: str, proxy: str = "") -> dict:
    """从视频 URL 解析元数据（标题、创作者/UP主、封面、时长）。"""
    url = url.strip()
    if not url:
        return {"ok": False, "error": "URL 不能为空"}
    if _is_bilibili_url(url):
        # 解析短链接 b23.tv
        if "b23.tv" in url.lower():
            try:
                r = httpx.get(url, follow_redirects=False, timeout=8.0)
                loc = r.headers.get("location")
                if loc:
                    url = loc
            except Exception:
                pass
        bv_match = re.search(r"(BV[a-zA-Z0-9]{10})", url, re.I)
        aid_match = re.search(r"av(\d+)", url, re.I)
        if not bv_match and not aid_match:
            return {"ok": False, "error": "未识别到有效的 Bilibili 视频号 (BV/av)"}
        bvid = ("BV" + bv_match.group(1)[2:]) if bv_match else None
        aid = aid_match.group(1) if aid_match else None
        api_url = (
            f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
            if bvid
            else f"https://api.bilibili.com/x/web-interface/view?aid={aid}"
        )
        try:
            with httpx.Client(trust_env=False, timeout=10.0) as client:
                res = client.get(api_url, headers={"User-Agent": "Mozilla/5.0"})
                data = res.json()
                if data.get("code") == 0:
                    v = data.get("data", {})
                    cover_pic = v.get("pic", "")
                    if cover_pic.startswith("//"):
                        cover_pic = "https:" + cover_pic
                    elif cover_pic.startswith("http://"):
                        cover_pic = "https://" + cover_pic[7:]
                    return {
                        "ok": True,
                        "title": v.get("title", ""),
                        "author": v.get("owner", {}).get("name", ""),
                        "cover_url": cover_pic,
                        "duration": v.get("duration", 0),
                        "url": url,
                        "kind": "stream_archive",
                    }
                return {"ok": False, "error": data.get("message", "获取 Bilibili 视频信息失败")}
        except Exception as exc:
            return {"ok": False, "error": f"请求 Bilibili 接口失败: {exc}"}

    # 其他站点通过 yt-dlp
    ytdlp = shutil.which("yt-dlp")
    if not ytdlp:
        return {"ok": False, "error": "yt-dlp 未安装"}
    ffmpeg_bin = _system_which("ffmpeg")
    cmd = [
        ytdlp, "--skip-download", "--dump-single-json", "--no-playlist",
        "--no-warnings", "--socket-timeout", "15",
    ]
    if ffmpeg_bin:
        cmd.extend(["--ffmpeg-location", ffmpeg_bin])
    if proxy:
        cmd.extend(["--proxy", proxy])
    cmd.append(url)
    try:
        import subprocess as _sp
        proc = _sp.run(
            cmd,
            stdin=_sp.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=25,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            lines = [l.strip() for l in proc.stdout.splitlines() if l.strip().startswith("{")]
            if lines:
                info = json.loads(lines[-1])
                return {
                    "ok": True,
                    "title": info.get("title", ""),
                    "author": info.get("uploader") or info.get("channel") or info.get("artist") or info.get("creator") or "",
                    "cover_url": info.get("thumbnail", ""),
                    "duration": info.get("duration", 0),
                    "url": url,
                    "kind": "stream_archive",
                }
        err_msg = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "无法解析视频信息"
        return {"ok": False, "error": err_msg}
    except Exception as exc:
        return {"ok": False, "error": f"解析失败: {exc}"}


def _download_bilibili_audio(
    url: str,
    tmp_dir: Path,
    *,
    status_cb: "Callable[[str], None]" | None = None,
    cancelled: "Callable[[], bool]" | None = None,
) -> tuple[Path, str, str, Path | None]:
    """直接通过 Bilibili 官方 API 下载音轨及封面（绕过 yt-dlp 412 反爬风控）。"""
    if "b23.tv" in url.lower():
        try:
            r = httpx.get(url, follow_redirects=False, timeout=8.0)
            loc = r.headers.get("location")
            if loc:
                url = loc
        except Exception:
            pass

    bv_match = re.search(r"(BV[a-zA-Z0-9]{10})", url, re.I)
    aid_match = re.search(r"av(\d+)", url, re.I)
    if not bv_match and not aid_match:
        raise ValueError("未识别到有效的 Bilibili 视频号 (BV/av)")

    bvid = ("BV" + bv_match.group(1)[2:]) if bv_match else None
    aid = aid_match.group(1) if aid_match else None
    api_url = (
        f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
        if bvid
        else f"https://api.bilibili.com/x/web-interface/view?aid={aid}"
    )

    if status_cb:
        status_cb("正在获取 Bilibili 视频信息…")

    with httpx.Client(trust_env=False, timeout=15.0) as client:
        res = client.get(api_url, headers={"User-Agent": "Mozilla/5.0"})
        data = res.json()
        if data.get("code") != 0:
            err = data.get("message", "未知错误")
            raise ValueError(f"Bilibili API 错误: {err}")

        view = data["data"]
        bvid = view.get("bvid") or bvid or f"av{aid}"
        cid = view.get("cid")
        title = view.get("title", "")
        author = view.get("owner", {}).get("name", "")
        pic_url = view.get("pic", "")
        if pic_url.startswith("//"):
            pic_url = "https:" + pic_url
        elif pic_url.startswith("http://"):
            pic_url = "https://" + pic_url[7:]

        p_match = re.search(r"[?&]p=(\d+)", url)
        pages = view.get("pages", [])
        if p_match and pages:
            try:
                p_idx = int(p_match.group(1)) - 1
                if 0 <= p_idx < len(pages):
                    cid = pages[p_idx].get("cid", cid)
                    part_title = pages[p_idx].get("part", "")
                    if part_title and part_title != title:
                        title = f"{title} - {part_title}"
            except (ValueError, IndexError):
                pass

        if cancelled and cancelled():
            raise _DownloadCancelled()

        if status_cb:
            status_cb("正在解析 Bilibili 音频流…")

        play_url = f"https://api.bilibili.com/x/player/wbi/playurl?bvid={bvid}&cid={cid}&fnval=16"
        play_res = client.get(
            play_url,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com"},
        ).json()
        dash = play_res.get("data", {}).get("dash")
        audio_list = dash.get("audio", []) if dash else []
        if not audio_list:
            raise ValueError("Bilibili 视频未返回可用的 DASH 音频流")

        # 按带宽降序取最高音质
        audio_list.sort(key=lambda a: a.get("bandwidth", 0), reverse=True)
        best_audio = audio_list[0]
        audio_stream_url = best_audio.get("baseUrl") or best_audio.get("base_url")
        backup_urls = best_audio.get("backupUrl") or best_audio.get("backup_url") or []
        candidate_urls = [audio_stream_url] + [u for u in backup_urls if u]
        media_path = tmp_dir / f"{bvid}.m4a"

        if status_cb:
            status_cb("正在下载音频…")

        download_success = False
        last_err = None
        for stream_url in candidate_urls:
            if not stream_url:
                continue
            try:
                with client.stream(
                    "GET",
                    stream_url,
                    headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com"},
                ) as s:
                    s.raise_for_status()
                    total = int(s.headers.get("content-length") or 0)
                    downloaded = 0
                    last_reported = 0
                    with media_path.open("wb") as f:
                        for chunk in s.iter_bytes(chunk_size=65536):
                            if cancelled and cancelled():
                                raise _DownloadCancelled()
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total > 0 and status_cb and downloaded - last_reported >= 65536 * 16:
                                last_reported = downloaded
                                status_cb(f"正在下载音频 {int(downloaded * 100 / total)}%…")
                download_success = True
                break
            except _DownloadCancelled:
                raise
            except Exception as exc:
                last_err = exc
                media_path.unlink(missing_ok=True)
                continue
        if not download_success:
            raise ValueError(f"下载音频流失败: {last_err or '未知错误'}")

        cover_path = tmp_dir / f"{bvid}.jpg"
        if pic_url:
            try:
                pic_res = client.get(pic_url, headers={"User-Agent": "Mozilla/5.0"})
                if pic_res.status_code == 200:
                    cover_path.write_bytes(pic_res.content)
                else:
                    cover_path = None
            except Exception:
                cover_path = None
        else:
            cover_path = None

    return media_path, title, author, cover_path


def _download_and_import(
    library: LibraryStore,
    url: str,
    *,
    kind: ItemKind,
    rj_code: str | None,
    title: str | None,
    author: str | None,
    creator_ids: tuple[str, ...] = (),
    proxy: str = "",
    proc_cb: "Callable[[object | None], None]" | None = None,
    status_cb: "Callable[[str], None]" | None = None,
    cancelled: "Callable[[], bool]" | None = None,
) -> ImportResult:
    """Download audio from a YouTube/Bilibili URL via yt-dlp and import it.

    Runs in a worker thread (network + ffmpeg). yt-dlp extracts audio to
    m4a (--extract-audio) in a temp dir, then library.import_audio copies
    it into the library with the usual checksum/dedupe logic.
    """
    import subprocess as _sp
    import tempfile as _tf

    tmp_dir = Path(_tf.mkdtemp(prefix="subforge-dl-"))
    try:
        media: Path | None = None
        cover_file: Path | None = None

        if _is_bilibili_url(url):
            try:
                b_media, b_title, b_author, b_cover = _download_bilibili_audio(
                    url, tmp_dir, status_cb=status_cb, cancelled=cancelled
                )
                media = b_media
                if not title:
                    title = b_title
                if not author:
                    author = b_author
                cover_file = b_cover
            except _DownloadCancelled:
                raise
            except Exception as b_exc:
                logger.warning("Bilibili direct download failed, fallback to yt-dlp: %s", b_exc)

        if media is None:
            ytdlp = shutil.which("yt-dlp")
            if ytdlp is None:
                raise ValueError("yt-dlp 未安装：请先安装 yt-dlp 或 pip install yt-dlp")

            if status_cb:
                status_cb("正在通过 yt-dlp 下载…")

            ffmpeg_bin = _system_which("ffmpeg")
            base = [
                ytdlp,
                "--no-playlist",
                "--extract-audio",
                "--audio-format", "m4a",
                "--audio-quality", "0",
                "--write-thumbnail",
                "--convert-thumbnails", "jpg",
                "--write-info-json",
                "--windows-filenames",
                "--no-check-certificates",
                "--socket-timeout", "30",
                "--retries", "2",
                "--fragment-retries", "2",
                "-o", str(tmp_dir / "%(id)s.%(ext)s"),
            ]
            if ffmpeg_bin:
                base.extend(["--ffmpeg-location", ffmpeg_bin])
            if _is_bilibili_url(url):
                base.extend([
                    "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                    "--referer", "https://www.bilibili.com/",
                    "--add-header", "Origin:https://www.bilibili.com",
                ])

            url_arg = [url]
            if proxy:
                proxy_cmd = base + ["--proxy", proxy]
                direct_cmd = base
                if _is_bilibili_url(url):
                    attempts = [direct_cmd, proxy_cmd]
                else:
                    attempts = [proxy_cmd, direct_cmd]
            else:
                attempts = [base]
            attempts = [c + url_arg for c in attempts]

            import time as _time
            result = None
            for attempt in attempts:
                if cancelled and cancelled():
                    break
                result = _spawn_and_wait(attempt, proc_cb, timeout=180)
                if result.returncode == 0:
                    break
                for _ in range(2):
                    if cancelled and cancelled():
                        break
                    _time.sleep(2)
                    result = _spawn_and_wait(attempt, proc_cb, timeout=180)
                    if result.returncode == 0:
                        break
                if result and result.returncode == 0:
                    break

            if cancelled and cancelled():
                raise _DownloadCancelled()
            if result is None or result.returncode != 0:
                err_detail = (result.stderr.strip()[-300:] if result else "") or "未知错误"
                raise ValueError(f"yt-dlp 下载失败：{err_detail}")

            info_files = [p for p in tmp_dir.iterdir() if p.is_file() and p.suffix.lower() == ".json"]
            if info_files:
                try:
                    info_data = json.loads(info_files[0].read_text(encoding="utf-8"))
                    if not title:
                        title = info_data.get("title")
                    if not author:
                        author = (
                            info_data.get("uploader")
                            or info_data.get("channel")
                            or info_data.get("artist")
                            or info_data.get("creator")
                        )
                except Exception:
                    pass

            audio_files = [
                p for p in tmp_dir.iterdir()
                if p.is_file() and p.suffix.lower() in {".m4a", ".mp3", ".opus", ".wav", ".flac"}
            ]
            if not audio_files:
                raise ValueError("yt-dlp 未提取到音频文件")
            media = audio_files[0]

            thumbs = [
                p for p in tmp_dir.iterdir()
                if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
            ]
            if thumbs:
                cover_file = thumbs[0]

        if status_cb:
            status_cb("正在写入作品库…")

        fallback_title = title or media.stem
        if not author and not creator_ids and kind == ItemKind.STREAM_ARCHIVE:
            author = "网络导入"

        result = library.import_audio(ImportRequest(
            source=media,
            kind=kind,
            title=fallback_title,
            rj_code=rj_code,
            author=author,
            creator_ids=creator_ids,
            source_url=url,
        ))
        if cover_file and cover_file.exists():
            try:
                from subforge.ui.covers import replace_cover
                replace_cover(library.root, result.item_id, cover_file)
                library.set_cover_source(result.item_id, "source_download")
            except Exception:
                try:
                    from subforge.ui.covers import covers_dir
                    covers_dir(library.root).mkdir(parents=True, exist_ok=True)
                    dst = covers_dir(library.root) / f"{result.item_id}.jpg"
                    if not dst.exists():
                        shutil.copy(cover_file, dst)
                        library.set_cover_source(result.item_id, "source_download")
                except OSError:
                    pass
        return result
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _resolve_selected_path(runtime: UiRuntime, form: dict[str, str], field: str) -> Path | None:
    selection_id = form.get(f"{field}_selection", "")
    if selection_id:
        selected = runtime.selections.pop(selection_id, None)
        if selected is not None:
            _cleanup_upload_selection(runtime, selection_id, selected)
        return selected
    value = form.get(field, "").strip()
    return Path(value) if value else None


async def _read_form_values(request: Request) -> dict[str, list[str]]:
    ct = request.headers.get("content-type", "").lower()
    if "application/json" in ct:
        try:
            data = await request.json()
            res: dict[str, list[str]] = {}
            for k, v in data.items():
                if isinstance(v, list):
                    res[k] = [str(x) for x in v]
                else:
                    res[k] = [str(v) if v is not None else ""]
            return res
        except Exception:
            return {}
    if "multipart/form-data" in ct:
        try:
            body_bytes = await request.body()
            import email
            msg = email.message_from_bytes(b"Content-Type: " + ct.encode("latin1", errors="replace") + b"\r\n\r\n" + body_bytes)
            res: dict[str, list[str]] = {}
            for part in msg.walk():
                name = part.get_param("name", header="content-disposition")
                if name:
                    payload = part.get_payload(decode=True)
                    if payload is not None:
                        res.setdefault(name, []).append(payload.decode("utf-8", errors="replace"))
            return res
        except Exception:
            pass
    body = (await request.body()).decode("utf-8")
    return parse_qs(body, keep_blank_values=True)


async def _read_form(request: Request) -> dict[str, str]:
    values = await _read_form_values(request)
    return {key: entries[-1] for key, entries in values.items()}


def _creator_ids_from_form(
    library: LibraryStore,
    values: dict[str, list[str]],
    item_kind: ItemKind | None = None,
) -> list[str]:
    creator_ids = list(dict.fromkeys(value for value in values.get("creator_ids", []) if value))
    new_name = values.get("new_creator_name", [""])[-1].strip()
    if new_name:
        new_kind = CreatorKind(values.get("new_creator_kind", [CreatorKind.VOICE_ACTOR.value])[-1])
        if item_kind == ItemKind.STREAM_ARCHIVE and new_kind != CreatorKind.VOICE_ACTOR:
            raise ValueError("stream archives require voice actors only")
        creator_ids.append(library.create_creator(new_name, new_kind).creator_id)
    return creator_ids


_DIR_SIZE_CACHE: dict[str, tuple[int, int]] = {}


def _item_directory_sizes(root: Path, items: list) -> dict[str, int]:
    sizes: dict[str, int] = {}
    for item in items:
        if item.kind != ItemKind.RJ_WORK:
            sizes[item.item_id] = sum(track.size for track in item.tracks)
            continue
        item_dir = root / item.directory
        try:
            mtime_ns = item_dir.stat().st_mtime_ns
            if item.item_id in _DIR_SIZE_CACHE:
                cached_mtime, cached_size = _DIR_SIZE_CACHE[item.item_id]
                if cached_mtime == mtime_ns:
                    sizes[item.item_id] = cached_size
                    continue
            total = 0
            for path in item_dir.rglob("*"):
                if path.is_file():
                    try:
                        total += path.stat().st_size
                    except OSError:
                        continue
            _DIR_SIZE_CACHE[item.item_id] = (mtime_ns, total)
            sizes[item.item_id] = total
        except OSError:
            sizes[item.item_id] = sum(track.size for track in item.tracks)
    return sizes


def _extract_item_tags(it) -> list[str]:
    explicit = list(getattr(it, "tags", []))
    if explicit:
        return explicit
    tags = set()
    title_text = str(getattr(it, "title", "") or "")
    for m in re.findall(r'#([^\s#\[\]【】_]+)', title_text):
        if len(m) > 1 and not m.startswith('202'):
            tags.add(m)
    for m in re.findall(r'[\[【]([^\]】]+)[\]】]', title_text):
        for part in re.split(r'[\s,，、/]+', m):
            clean = part.lstrip('#').strip()
            if 1 < len(clean) < 15 and not clean.startswith('202') and not clean.startswith('BV'):
                tags.add(clean)
    common_keywords = [
        '耳舐め', '舔耳', 'ASMR', 'KU100', '囁き', '催眠', '安眠',
        'マッサージ', '采耳', '甘サド', '双耳', '耳かき', '吐息', 'バイノーラル'
    ]
    for kw in common_keywords:
        if kw.lower() in title_text.lower():
            tags.add(kw)
    rj = getattr(it, "rj_code", None)
    if rj:
        tags.discard(rj)
    return sorted(tags)


def _track_duration_seconds(library: LibraryStore, track) -> float:
    for language in (track.source_language, track.target_language):
        path = library.track_subtitle_path(track.track_id, language)
        if not path.is_file():
            continue
        try:
            entries = read_srt(path)
        except Exception:
            continue
        if entries:
            return max(entry.end for entry in entries)
    return 0.0


def _format_duration(total_seconds: float) -> str:
    total = max(0, int(round(total_seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def _track_duration_label(library: LibraryStore, track) -> str:
    seconds = _track_duration_seconds(library, track)
    return _format_duration(seconds) if seconds else "--:--"


def _creator_duration(library: LibraryStore, items: list) -> float:
    duration = 0.0
    for item in items:
        for track in item.tracks:
            path = library.track_subtitle_path(track.track_id, track.source_language)
            if not path.exists():
                continue
            try:
                entries = read_srt(path)
            except Exception:
                continue
            if entries:
                duration += max(entry.end for entry in entries)
    return duration
