from __future__ import annotations

import asyncio
import hmac
import json
import mimetypes
import secrets
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs
from uuid import uuid4

from jinja2 import Environment, PackageLoader, select_autoescape
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from subforge.asr.model_manager import cached_models
from subforge.config import DEFAULT_MODELS_DIR
from subforge.library import ImportRequest, ItemKind, LibraryStore
from subforge.translate.srt_io import read_srt
from subforge.ui.checks import check_model_configuration, test_profile_connection
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
                self.library, self.deps.worker, self.deps.settings.get_media_concurrency(),
                profile_resolver=self.deps.profiles.resolve,
                deepgram_key_resolver=self.deps.settings.get_deepgram_api_key,
                proxy_resolver=self.deps.settings.get_proxy_url,
                models_dir_resolver=self.deps.settings.get_models_dir,
                direct_model_resolver=self.deps.settings.get_direct_model_path,
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
        html = self.templates.get_template(name).render(
            request=request,
            csrf_token=csrf,
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
        return runtime.render(
            "index.html",
            request,
            items=library.list_items(),
            profiles=deps.profiles.list_public(),
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
        selected = await asyncio.to_thread(deps.picker.choose_directory)
        if selected is None:
            return RedirectResponse("/", status_code=303)
        if runtime.tasks is not None:
            await runtime.tasks.close()
        if runtime.library is not None:
            runtime.library.close()
        runtime.library = LibraryStore.initialize(selected)
        runtime.tasks = TaskManager(
            runtime.library, deps.worker, deps.settings.get_media_concurrency(),
            profile_resolver=deps.profiles.resolve,
            deepgram_key_resolver=deps.settings.get_deepgram_api_key,
            proxy_resolver=deps.settings.get_proxy_url,
            models_dir_resolver=deps.settings.get_models_dir,
            direct_model_resolver=deps.settings.get_direct_model_path,
        )
        deps.settings.set_active_library(selected)
        return RedirectResponse("/", status_code=303)

    async def choose_directory(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        selected = await asyncio.to_thread(deps.picker.choose_directory)
        if selected is None:
            return JSONResponse({"cancelled": True})
        selection_id = uuid4().hex
        runtime.selections[selection_id] = selected.resolve()
        return JSONResponse({"selection_id": selection_id, "name": selected.name})

    async def choose_audio(request: Request) -> Response:
        error = await _authorize_write(request, runtime)
        if error:
            return error
        selected = await asyncio.to_thread(deps.picker.choose_audio)
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
        form = await _read_form(request)
        selection_id = form.get("selection_id", "")
        source = runtime.selections.pop(selection_id, None)
        if source is None:
            return JSONResponse({"error": "Invalid or expired selection"}, status_code=400)
        try:
            result = await asyncio.to_thread(
                library.import_audio,
                ImportRequest(
                    source=source,
                    kind=ItemKind(form.get("kind", "")),
                    title=form.get("title", source.stem),
                    rj_code=form.get("rj_code") or None,
                    author=form.get("author") or None,
                ),
            )
        except (ValueError, OSError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return RedirectResponse(f"/items/{result.item_id}", status_code=303)

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
        default_model = (
            latest_snapshot.get("whisper_model") if latest_snapshot
            else next((name for name in ("large-v3", "medium", "base") if name in cached), "medium")
        )
        return runtime.render(
            "detail.html", request, item=item, task_by_track=task_by_track,
            profiles=deps.profiles.list_public(), models=model_names,
            cached_models=cached, direct_models=direct_models, default_model=default_model,
            latest_snapshot=latest_snapshot,
        )

    async def settings_page(request: Request) -> Response:
        if request.method == "POST":
            error = await _authorize_write(request, runtime)
            if error:
                return error
            form = await _read_form(request)
            try:
                if form.get("deepgram_api_key"):
                    deps.settings.set_deepgram_api_key(form["deepgram_api_key"])
                deps.settings.set_media_concurrency(int(form.get("media_concurrency", "1")))
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
            media_concurrency=deps.settings.get_media_concurrency(),
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
        return runtime.render("player.html", request, item=item, track=track)

    async def track_media(request: Request) -> Response:
        library = runtime.open_active_library()
        if library is None:
            return Response("Not found", status_code=404)
        try:
            path = library.track_media_path(request.path_params["track_id"])
        except KeyError:
            return Response("Not found", status_code=404)
        return _range_response(path, request.headers.get("range"))

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
            async for event in runtime.tasks.subscribe(task_id):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

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
        Route("/picker/directory", choose_directory, methods=["POST"]),
        Route("/items/import", import_item, methods=["POST"]),
        Route("/items/{item_id}", item_detail),
        Route("/items/{item_id}/trash", trash_item, methods=["POST"]),
        Route("/settings", settings_page, methods=["GET", "POST"]),
        Route("/settings/deepgram/delete-key", delete_deepgram_key, methods=["POST"]),
        Route("/profiles", profiles_page, methods=["GET", "POST"]),
        Route("/profiles/{profile_id}/test", test_profile, methods=["POST"]),
        Route("/profiles/{profile_id}/delete", delete_profile, methods=["POST"]),
        Route("/profiles/{profile_id}/delete-key", delete_profile_key, methods=["POST"]),
        Route("/settings/models/{model}/check", check_model, methods=["POST"]),
        Route("/tracks/{track_id}/process", start_task, methods=["POST"]),
        Route("/tracks/{track_id}/play", player_page),
        Route("/tracks/{track_id}/media", track_media),
        Route("/tracks/{track_id}/subtitles/{language}", track_subtitles),
        Route("/tasks/{task_id}", task_status),
        Route("/tasks/{task_id}/events", task_events),
        Route("/tasks/{task_id}/cancel", cancel_task, methods=["POST"]),
    ]
    @asynccontextmanager
    async def lifespan(app):
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
        with path.open("rb") as handle:
            handle.seek(start)
            remaining = end - start + 1
            while remaining:
                data = handle.read(min(64 * 1024, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    headers.update({
        "Content-Range": f"bytes {start}-{end}/{size}",
        "Content-Length": str(end - start + 1),
    })
    return StreamingResponse(chunk(), status_code=206, media_type=content_type, headers=headers)


def _resolve_selected_path(runtime: UiRuntime, form: dict[str, str], field: str) -> Path | None:
    selection_id = form.get(f"{field}_selection", "")
    if selection_id:
        return runtime.selections.pop(selection_id, None)
    value = form.get(field, "").strip()
    return Path(value) if value else None


async def _read_form(request: Request) -> dict[str, str]:
    body = (await request.body()).decode("utf-8")
    return {key: values[-1] for key, values in parse_qs(body, keep_blank_values=True).items()}
