from __future__ import annotations

import asyncio
import hmac
import json
import logging
import mimetypes
import secrets
import shutil
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs
from uuid import uuid4

from jinja2 import Environment, PackageLoader, select_autoescape
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from subforge.asr.model_manager import cached_models
from subforge import __version__
from subforge.config import DEFAULT_MODELS_DIR
from subforge.library import CreatorKind, ImportRequest, ItemKind, LibraryStore
from subforge.translate.srt_io import read_srt
from subforge.ui.checks import check_model_configuration, test_profile_connection
from subforge.ui.covers import cover_for_item, covers_dir, replace_cover
from subforge.ui.picker import FilePicker
from subforge.ui.profiles import LlmProfileStore, mask_secret
from subforge.ui.settings import UiSettingsStore
from subforge.ui.tasks import ProcessingSnapshot, TaskManager, WorkerAdapter


@dataclass
class UiDependencies:
    settings: UiSettingsStore
    picker: FilePicker
    profiles: LlmProfileStore
    worker: WorkerAdapter
    startup_token: str
    open_browser: bool = True
    allowed_hosts: set[str] = field(default_factory=lambda: {"127.0.0.1", "localhost"})
    media_concurrency: int = 1


class UiRuntime:
    def __init__(self, deps: UiDependencies) -> None:
        self.deps = deps
        self.sessions: dict[str, str] = {}
        self.selections: dict[str, Path] = {}
        self.imports: dict[str, dict] = {}  # 后台 URL 下载导入任务状态
        self.library: LibraryStore | None = None
        self.tasks: TaskManager | None = None
        self.templates = Environment(
            loader=PackageLoader("subforge.ui", "templates"),
            autoescape=select_autoescape(["html", "xml"]),
        )

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
        # iframe 外壳：内页请求（iframe 加载）只渲染内容块，不渲染顶层外壳
        is_frame = request.headers.get("sec-fetch-dest") == "iframe"
        html = self.templates.get_template(name).render(
            request=request,
            csrf_token=csrf,
            is_frame=is_frame,
            **context,
        )
        return HTMLResponse(html)


def create_app(deps: UiDependencies) -> Starlette:
    runtime = UiRuntime(deps)

    async def homepage(request: Request) -> Response:
        token = request.query_params.get("token")
        if token is not None:
            if not deps.startup_token or not hmac.compare_digest(token, deps.startup_token):
                return Response("Invalid startup token", status_code=401)
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
        if _session_csrf(request, runtime) is None:
            return Response("Authentication required", status_code=401)
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
        items = library.list_items(selected_creator_ids)
        item_size_by_id = await asyncio.to_thread(_item_directory_sizes, library.root, items)
        return runtime.render(
            "index.html",
            request,
            items=items,
            creators=creators,
            creator_by_id={creator.creator_id: creator for creator in creators},
            selected_creator_ids=set(selected_creator_ids),
            profiles=deps.profiles.list_public(),
            item_size_by_id=item_size_by_id,
        )

    async def session_info(request: Request) -> Response:
        csrf = _session_csrf(request, runtime)
        if csrf is None:
            return JSONResponse({"error": "authentication required"}, status_code=401)
        return JSONResponse({"csrf_token": csrf})

    async def select_library(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        # tkinter 对话框必须在主线程运行（Tcl 非线程安全）
        selected = deps.picker.choose_directory()
        if selected is None:
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
        )
        deps.settings.set_active_library(selected)
        return RedirectResponse("/", status_code=303)

    async def choose_directory(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        # tkinter 对话框必须在主线程运行（Tcl 非线程安全）
        selected = deps.picker.choose_directory()
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
        selected = deps.picker.choose_audio()
        if selected is None:
            return JSONResponse({"cancelled": True})
        selection_id = uuid4().hex
        runtime.selections[selection_id] = selected.resolve()
        return JSONResponse({"selection_id": selection_id, "filename": selected.name})

    async def choose_media_folder(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        selected = deps.picker.choose_media_folder()
        if selected is None:
            return JSONResponse({"cancelled": True})
        selection_id = uuid4().hex
        runtime.selections[selection_id] = selected.resolve()
        return JSONResponse({"selection_id": selection_id, "name": selected.name})

    async def choose_image(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        selected = deps.picker.choose_image()
        if selected is None:
            return JSONResponse({"cancelled": True})
        selection_id = uuid4().hex
        runtime.selections[selection_id] = selected.resolve()
        return JSONResponse({"selection_id": selection_id, "filename": selected.name})

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
        source = runtime.selections.pop(selection_id, None)
        if source is None:
            return JSONResponse({"error": "Invalid or expired selection"}, status_code=400)
        try:
            kind = ItemKind(form.get("kind", ""))
            result = await asyncio.to_thread(
                library.import_audio,
                ImportRequest(
                    source=source,
                    kind=kind,
                    title=form.get("title", source.stem),
                    rj_code=form.get("rj_code") or None,
                    author=form.get("author") or None,
                    creator_ids=tuple(_creator_ids_from_form(library, values, kind)),
                ),
            )
        except (ValueError, OSError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
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
        runtime.imports[task_id] = {
            "task_id": task_id, "kind": "download", "status": "running",
            "stage": "download", "message": "开始下载…", "item_id": None,
            "source_url": url,
            "item_kind": kind.value,
            "rj_code": form.get("rj_code") or None,
            "title": form.get("title") or None,
            "author": form.get("author") or None,
            "creator_ids": list(creator_ids),
        }
        await _run_url_import(
            runtime, library, url, task_id,
            kind=kind,
            rj_code=form.get("rj_code") or None,
            title=form.get("title") or None,
            author=form.get("author") or None,
            creator_ids=tuple(creator_ids),
        )
        return JSONResponse({"task_id": task_id, "status": "running"}, status_code=202)

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
            return JSONResponse({"error": "RJ code is required"}, status_code=400)
        task_id = uuid4().hex
        runtime.imports[task_id] = {
            "task_id": task_id, "kind": "media_import", "status": "running",
            "stage": "scan", "message": "扫描目录…", "item_id": None,
            "source_url": folder.name, "progress": 0.0,
            "completed": 0, "total": 0, "imported": 0, "duplicates": 0, "failed": 0,
        }
        await _run_folder_import(
            runtime, library, folder, task_id,
            rj_code=rj_code, title=form.get("title") or None,
            creator_ids=tuple(_creator_ids_from_form(library, values, ItemKind.RJ_WORK)),
        )
        return JSONResponse({"task_id": task_id, "status": "running"}, status_code=202)

    async def import_status(request: Request) -> Response:
        """查询后台下载导入任务状态（前端轮询）。"""
        task = runtime.imports.get(request.path_params["task_id"])
        if task is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(task)

    async def item_detail(request: Request) -> Response:
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
        return runtime.render(
            "detail.html", request, item=item, task_by_track=task_by_track,
            profiles=public_profiles, models=model_names,
            cached_models=cached, direct_models=direct_models, default_model=default_model,
            latest_snapshot=latest_snapshot, creators=creators,
            creator_by_id={creator.creator_id: creator for creator in creators},
            track_media_available=track_media_available,
            track_subtitle_available=track_subtitle_available,
            track_durations=track_durations,
            default_profile_id=default_profile_id,
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
        library = runtime.open_active_library()
        processing_tasks = []
        if library is not None and runtime.tasks is not None:
            queued_position = 0
            for task in reversed(runtime.tasks.list_tasks()):
                if task.status == "queued":
                    queued_position += 1
                try:
                    item, track = library.get_track(task.track_id)
                except KeyError:
                    continue
                processing_tasks.append({
                    "task": task,
                    "item": item,
                    "track": track,
                    "queue_position": queued_position if task.status == "queued" else None,
                })
            processing_tasks.reverse()
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
            processing_tasks=processing_tasks,
            import_tasks=list(reversed(list(runtime.imports.values()))),
        )

    async def about_page(request: Request) -> Response:
        return runtime.render("about.html", request, version=__version__)

    async def settings_page(request: Request) -> Response:
        if request.method == "POST":
            error = await _authorize_write(request, runtime)
            if error:
                return error
            form = await _read_form(request)
            try:
                if form.get("deepgram_api_key"):
                    deps.settings.set_deepgram_api_key(form["deepgram_api_key"])
                deps.settings.set_asr_concurrency(int(form.get("asr_concurrency", "1")))
                deps.settings.set_translate_workers(int(form.get("translate_workers", "8")))
                deps.settings.set_proxy_url(form.get("proxy_url", ""))
                models_dir = _resolve_selected_path(runtime, form, "models_dir")
                if models_dir:
                    deps.settings.set_models_dir(models_dir)
                for model in ("medium", "large-v3"):
                    value = _resolve_selected_path(runtime, form, f"direct_{model}")
                    deps.settings.set_direct_model_path(model, value)
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
            return RedirectResponse("/settings", status_code=303)
        return runtime.render(
            "settings.html", request,
            deepgram_key_masked=deps.settings.deepgram_key_display(),
            deepgram_key_configured=bool(deps.settings.get_deepgram_api_key()),
            deepgram_key_deletable=deps.settings.has_stored_deepgram_api_key(),
            asr_concurrency=deps.settings.get_asr_concurrency(),
            translate_workers=deps.settings.get_translate_workers(),
            proxy_url=deps.settings.get_proxy_url(),
            models_dir=deps.settings.get_models_dir(),
            direct_medium=deps.settings.get_direct_model_path("medium"),
            direct_large_v3=deps.settings.get_direct_model_path("large-v3"),
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
        ok, message = await test_profile_connection(profile)
        return JSONResponse({"ok": ok, "message": message})

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
                return JSONResponse({"error": str(exc)}, status_code=400)
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
        if request.method == "POST":
            error = await _authorize_write(request, runtime)
            if error:
                return error
            form = await _read_form(request)
            try:
                deps.profiles.save(
                    name=form.get("name", ""),
                    base_url=form.get("base_url", ""),
                    model=form.get("model", ""),
                    api_key=form.get("api_key", ""),
                    profile_id=form.get("profile_id") or None,
                    proxy_url=form.get("proxy_url", ""),
                    verify_tls=form.get("verify_tls") == "on",
                    ca_bundle=form.get("ca_bundle", ""),
                )
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
            return RedirectResponse("/profiles", status_code=303)
        return runtime.render("profiles.html", request, profiles=deps.profiles.list_public())

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
            profile = deps.profiles.resolve(form.get("llm_profile_id", ""))
            selected_snapshot = ProcessingSnapshot(
                asr_provider=form.get("asr_provider", "local"),
                scene=form.get("scene", "normal"),
                whisper_model=form.get("whisper_model", "medium"),
                llm_profile_id=profile.profile_id,
            )
            mode = form.get("mode", "from_scratch")
            for track in item.tracks:
                latest = runtime.tasks.latest_for_track(track.track_id)
                if track.status == "playable" or (latest and latest.status in {"queued", "running"}):
                    continue
                snapshot = selected_snapshot
                if mode == "continue" and latest and latest.config_snapshot:
                    snapshot = ProcessingSnapshot(**latest.config_snapshot)
                    deps.profiles.resolve(snapshot.llm_profile_id)
                await runtime.tasks.enqueue(track.track_id, snapshot, mode=mode)
        except KeyError:
            return JSONResponse({"error": "LLM profile not found"}, status_code=404)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
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
        return RedirectResponse(f"/items/{item.item_id}", status_code=303)

    async def start_task(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        library = runtime.open_active_library()
        if library is None or runtime.tasks is None:
            return JSONResponse({"error": "Library is not configured"}, status_code=409)
        form = await _read_form(request)
        mode = form.get("mode", "continue")
        previous = runtime.tasks.latest_for_track(request.path_params["track_id"])
        try:
            if mode == "continue" and previous and previous.config_snapshot:
                snapshot = ProcessingSnapshot(**previous.config_snapshot)
            else:
                profile_id = form.get("llm_profile_id", "")
                profile = deps.profiles.resolve(profile_id)
                snapshot = ProcessingSnapshot(
                    asr_provider=form.get("asr_provider", "local"),
                    scene=form.get("scene", "normal"),
                    whisper_model=form.get("whisper_model", "medium"),
                    llm_profile_id=profile.profile_id,
                )
            deps.profiles.resolve(snapshot.llm_profile_id)
            task = await runtime.tasks.enqueue(
                request.path_params["track_id"], snapshot, mode=mode,
            )
        except KeyError:
            return JSONResponse({"error": "Track or LLM profile not found"}, status_code=404)
        return RedirectResponse(f"/items/{library.get_track(task.track_id)[0].item_id}", status_code=303)

    async def player_page(request: Request) -> Response:
        library = runtime.open_active_library()
        if library is None:
            return Response("Not found", status_code=404)
        try:
            item, track = library.get_track(request.path_params["track_id"])
        except KeyError:
            return Response("Not found", status_code=404)
        return runtime.render("player.html", request, item=item, track=track,
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
        item_id = request.path_params["item_id"]
        try:
            library.get_item(item_id)
            replace_cover(library.root, item_id, selected)
            library.set_cover_source(item_id, "manual_upload")
        except KeyError:
            return Response("Not found", status_code=404)
        except (ValueError, OSError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return RedirectResponse(f"/items/{item_id}", status_code=303)

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
        cover_path = cover_for_item(library.root, item.item_id, media_path)
        if cover_path is not None and item.cover_source is None:
            library.set_cover_source(item.item_id, "embedded")
        if cover_path is None:
            return Response("Not found", status_code=404)
        return FileResponse(cover_path, media_type="image/jpeg")

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
        if task.status != "failed":
            return JSONResponse({"error": "只有失败的任务可以重试"}, status_code=409)
        if not task.config_snapshot:
            return JSONResponse({"error": "该任务没有可用的配置快照，无法重试"}, status_code=400)
        try:
            snapshot = ProcessingSnapshot(**task.config_snapshot)
            deps.profiles.resolve(snapshot.llm_profile_id)
        except KeyError:
            return JSONResponse({"error": "LLM 配置不存在，无法重试"}, status_code=404)
        except TypeError:
            return JSONResponse({"error": "任务配置快照损坏，无法重试"}, status_code=400)
        await runtime.tasks.enqueue(task.track_id, snapshot, mode="continue")
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
        task.update(status="running", stage="download", message="开始重试下载…", item_id=None)
        await _run_url_import(
            runtime, library, url, task["task_id"],
            kind=ItemKind(task.get("item_kind") or "stream_archive"),
            rj_code=task.get("rj_code"), title=task.get("title"), author=task.get("author"),
            creator_ids=tuple(task.get("creator_ids") or ()),
        )
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
        return RedirectResponse("/", status_code=303)

    routes = [
        Mount("/static", StaticFiles(packages=[("subforge.ui", "static")]), name="static"),
        Route("/", homepage),
        Route("/api/session", session_info),
        Route("/library/select", select_library, methods=["POST"]),
        Route("/library/rescan", rescan, methods=["POST"]),
        Route("/picker/audio", choose_audio, methods=["POST"]),
        Route("/picker/media-folder", choose_media_folder, methods=["POST"]),
        Route("/picker/image", choose_image, methods=["POST"]),
        Route("/api/selections/{selection_id}/image", selected_image_preview),
        Route("/picker/directory", choose_directory, methods=["POST"]),
        Route("/items/import", import_item, methods=["POST"]),
        Route("/items/import-url", import_item_url, methods=["POST"]),
        Route("/api/import-folders/preview", preview_folder_import, methods=["POST"]),
        Route("/items/import-folder", import_folder, methods=["POST"]),
        Route("/api/imports/{task_id}", import_status),
        Route("/api/creators", create_creator_api, methods=["POST"]),
        Route("/items/{item_id}", item_detail),
        Route("/items/{item_id}/edit", edit_item, methods=["POST"]),
        Route("/items/{item_id}/process", process_item, methods=["POST"]),
        Route("/items/{item_id}/trash", trash_item, methods=["POST"]),
        Route("/items/{item_id}/cover", replace_item_cover, methods=["POST"]),
        Route("/covers/{item_id}", item_cover),
        Route("/settings", settings_page, methods=["GET", "POST"]),
        Route("/settings/deepgram/delete-key", delete_deepgram_key, methods=["POST"]),
        Route("/stats", stats_page),
        Route("/downloads", downloads_page),
        Route("/about", about_page),
        Route("/creators", creators_page, methods=["GET", "POST"]),
        Route("/profiles", profiles_page, methods=["GET", "POST"]),
        Route("/profiles/{profile_id}/test", test_profile, methods=["POST"]),
        Route("/profiles/{profile_id}/delete", delete_profile, methods=["POST"]),
        Route("/profiles/{profile_id}/delete-key", delete_profile_key, methods=["POST"]),
        Route("/settings/models/{model}/check", check_model, methods=["POST"]),
        Route("/tracks/{track_id}/process", start_task, methods=["POST"]),
        Route("/tracks/{track_id}/rename", rename_track, methods=["POST"]),
        Route("/tracks/{track_id}/delete", delete_track, methods=["POST"]),
        Route("/tracks/{track_id}/play", player_page),
        Route("/tracks/{track_id}/media", track_media),
        Route("/tracks/{track_id}/subtitles/{language}", track_subtitles),
        Route("/tracks/{track_id}/subtitles/{language}/download", download_track_subtitle),
        Route("/api/tasks/status", task_statuses),
        Route("/tasks/{task_id}", task_status),
        Route("/tasks/{task_id}/events", task_events),
        Route("/tasks/{task_id}/cancel", cancel_task, methods=["POST"]),
        Route("/tasks/{task_id}/retry", retry_task, methods=["POST"]),
        Route("/api/imports/{task_id}/retry", retry_import, methods=["POST"]),
    ]
    @asynccontextmanager
    async def lifespan(app):
        _quiet_proactor_reset_noise()
        yield
        await runtime.close()

    app = Starlette(routes=routes, lifespan=lifespan)

    async def require_read_session(request: Request, call_next):
        public_path = request.url.path.startswith("/static/")
        token_exchange = request.url.path == "/" and request.query_params.get("token") is not None
        if not public_path and not token_exchange and _session_csrf(request, runtime) is None:
            return Response("Authentication required", status_code=401)
        return await call_next(request)

    app.add_middleware(BaseHTTPMiddleware, dispatch=require_read_session)
    app.state.runtime = runtime
    return app


def _session_csrf(request: Request, runtime: UiRuntime) -> str | None:
    session_id = request.cookies.get("subforge_session")
    return runtime.sessions.get(session_id) if session_id else None


async def _authorize_write(request: Request, runtime: UiRuntime) -> Response | None:
    host = request.headers.get("host", "").split(":", 1)[0].lower()
    if host not in {value.lower() for value in runtime.deps.allowed_hosts}:
        return JSONResponse({"error": "invalid host"}, status_code=403)
    csrf = _session_csrf(request, runtime)
    if csrf is None:
        return JSONResponse({"error": "authentication required"}, status_code=401)
    origin = request.headers.get("origin")
    if origin not in {f"http://{request.headers.get('host')}", f"https://{request.headers.get('host')}"}:
        return JSONResponse({"error": "invalid origin"}, status_code=403)
    supplied = request.headers.get("x-csrf-token")
    if not supplied:
        body = (await request.body()).decode("utf-8")
        supplied = parse_qs(body, keep_blank_values=True).get("csrf_token", [""])[-1]
    if not supplied or not hmac.compare_digest(supplied, csrf):
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

    def _worker() -> None:
        try:
            _set("running", "下载中…")
            result = _download_and_import(
                library, url,
                kind=kind, rj_code=rj_code, title=title, author=author,
                creator_ids=creator_ids,
            )
            _set("done", "导入完成", result.item_id)
        except (ValueError, OSError) as exc:
            _set("error", str(exc))

    threading.Thread(target=_worker, daemon=True, name=f"url-import-{task_id[:8]}").start()


def _download_and_import(
    library: LibraryStore,
    url: str,
    *,
    kind: ItemKind,
    rj_code: str | None,
    title: str | None,
    author: str | None,
    creator_ids: tuple[str, ...] = (),
) -> ImportResult:
    """Download audio from a YouTube/Bilibili URL via yt-dlp and import it.

    Runs in a worker thread (network + ffmpeg). yt-dlp extracts audio to
    m4a (--extract-audio) in a temp dir, then library.import_audio copies
    it into the library with the usual checksum/dedupe logic.
    """
    import subprocess as _sp
    import tempfile as _tf

    ytdlp = shutil.which("yt-dlp")
    if ytdlp is None:
        raise ValueError("yt-dlp 未安装：请先安装 yt-dlp 或 pip install yt-dlp")
    tmp_dir = Path(_tf.mkdtemp(prefix="subforge-dl-"))
    try:
        # Bilibili 反爬：元数据 API 间歇性返回 412/403/405。模拟浏览器 UA + referer
        # + 浏览器 cookie（--cookies-from-browser）提高通过率；cookie 缺失时降级重试。
        cmd = [
            ytdlp,
            "--no-playlist",
            "--extract-audio",
            "--audio-format", "m4a",
            "--audio-quality", "0",
            "--write-thumbnail",
            "--convert-thumbnails", "jpg",
            "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "--referer", "https://www.bilibili.com/",
            "--add-header", "Origin:https://www.bilibili.com",
            "--no-check-certificates",
            "--retries", "3",
            "--fragment-retries", "3",
            "-o", str(tmp_dir / "%(title)s.%(ext)s"),
            url,
        ]
        result = _sp.run(cmd, capture_output=True, text=True, timeout=600)
        # Bilibili 反爬间歇性（412/403/405）：重试原始命令（短延时错开频控）
        if result.returncode != 0 and "bilibili.com" in url.lower():
            import time as _time
            for _ in range(2):
                _time.sleep(2)
                result = _sp.run(cmd, capture_output=True, text=True, timeout=600)
                if result.returncode == 0:
                    break
        if result.returncode != 0:
            raise ValueError(f"yt-dlp 下载失败：{result.stderr.strip()[-300:] or '未知错误'}")
        logger.info("yt-dlp downloaded files: %s", [p.name for p in tmp_dir.iterdir()])
        audio_files = [p for p in tmp_dir.iterdir() if p.is_file() and p.suffix.lower() in {".m4a", ".mp3", ".opus", ".wav", ".flac"}]
        if not audio_files:
            raise ValueError("yt-dlp 未提取到音频文件")
        media = audio_files[0]
        fallback_title = title or media.stem
        result = library.import_audio(ImportRequest(
            source=media,
            kind=kind,
            title=fallback_title,
            rj_code=rj_code,
            author=author,
            creator_ids=creator_ids,
            source_url=url,
        ))
        # 抓取到的封面 → 库封面缓存（.subforge/covers/{item_id}.jpg）
        # 无论新建还是去重复用：目标封面不存在就写入
        thumbs = [p for p in tmp_dir.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}]
        if thumbs:
            from subforge.ui.covers import covers_dir
            covers_dir(library.root).mkdir(parents=True, exist_ok=True)
            dst = covers_dir(library.root) / f"{result.item_id}.jpg"
            if not dst.exists():
                try:
                    shutil.copy(thumbs[0], dst)
                    library.set_cover_source(result.item_id, "source_download")
                except OSError:
                    pass
        return result
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _resolve_selected_path(runtime: UiRuntime, form: dict[str, str], field: str) -> Path | None:
    selection_id = form.get(f"{field}_selection", "")
    if selection_id:
        return runtime.selections.pop(selection_id, None)
    value = form.get(field, "").strip()
    return Path(value) if value else None


async def _read_form_values(request: Request) -> dict[str, list[str]]:
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


def _item_directory_sizes(root: Path, items: list) -> dict[str, int]:
    sizes: dict[str, int] = {}
    for item in items:
        if item.kind != ItemKind.RJ_WORK:
            continue
        total = 0
        item_dir = root / item.directory
        try:
            for path in item_dir.rglob("*"):
                if path.is_file():
                    try:
                        total += path.stat().st_size
                    except OSError:
                        continue
        except OSError:
            total = sum(track.size for track in item.tracks)
        sizes[item.item_id] = total
    return sizes


def _track_duration_label(library: LibraryStore, track) -> str:
    for language in (track.source_language, track.target_language):
        path = library.track_subtitle_path(track.track_id, language)
        if not path.is_file():
            continue
        try:
            entries = read_srt(path)
        except Exception:
            continue
        if entries:
            total = max(0, round(max(entry.end for entry in entries)))
            hours, remainder = divmod(total, 3600)
            minutes, seconds = divmod(remainder, 60)
            return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"
    return "--:--"


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
