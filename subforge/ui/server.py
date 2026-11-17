from __future__ import annotations

import os
import secrets
import threading
import webbrowser

import uvicorn

from subforge.config import DEFAULT_CONFIG_DIR
from subforge.ui.app import UiDependencies, create_app
from subforge.ui.model_profiles import ModelProfileStore
from subforge.ui.picker import default_file_picker
from subforge.ui.settings import UiSettingsStore
from subforge.ui.tasks import SubprocessWorkerAdapter


def run_ui(
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
    token: str | None = None,
    no_auth: bool = True,
    allowed_hosts: set[str] | None = None,
) -> None:
    """Run the Library Web UI (supports localhost or LAN/Tailscale hosting)."""
    settings = UiSettingsStore(DEFAULT_CONFIG_DIR / "ui.json")
    effective_token = token or settings.get_fixed_token()
    is_fixed = bool(token or settings.get_fixed_token())
    if effective_token and not no_auth:
        effective_no_auth = False
    else:
        effective_no_auth = no_auth or settings.get_no_auth()
    startup_token = "" if effective_no_auth else (effective_token or secrets.token_urlsafe(32))

    hosts = {"127.0.0.1", "localhost"}
    if host not in {"0.0.0.0", "::"}:
        hosts.add(host)
    if allowed_hosts:
        hosts.update(h.strip().lower() for h in allowed_hosts if h.strip())
    env_hosts = os.environ.get("SUBFORGE_ALLOWED_HOSTS", "")
    if env_hosts:
        hosts.update(h.strip().lower() for h in env_hosts.split(",") if h.strip())

    app = create_app(UiDependencies(
        settings=settings,
        picker=default_file_picker(),
        profiles=ModelProfileStore(
            DEFAULT_CONFIG_DIR / "model-profiles.json",
            legacy_llm_path=DEFAULT_CONFIG_DIR / "llm-profiles.json",
            legacy_gemini_path=DEFAULT_CONFIG_DIR / "gemini-audio-profiles.json",
        ),
        worker=SubprocessWorkerAdapter(),
        startup_token=startup_token,
        is_fixed_token=is_fixed,
        no_auth=effective_no_auth,
        open_browser=open_browser,
        allowed_hosts=hosts,
    ))
    display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    url = f"http://{display_host}:{port}/" if effective_no_auth else f"http://{display_host}:{port}/?token={startup_token}"
    if open_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    print(f"SubForge UI: {url}")
    uvicorn.run(app, host=host, port=port, access_log=False)
