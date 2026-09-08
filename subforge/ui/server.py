from __future__ import annotations

import secrets
import threading
import webbrowser

import uvicorn

from subforge.config import DEFAULT_CONFIG_DIR
from subforge.ui.app import UiDependencies, create_app
from subforge.ui.model_profiles import ModelProfileStore
from subforge.ui.picker import WindowsFilePicker
from subforge.ui.settings import UiSettingsStore
from subforge.ui.tasks import SubprocessWorkerAdapter


def run_ui(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    """Run the localhost-only Library UI."""
    if host != "127.0.0.1":
        raise ValueError("SubForge UI only supports 127.0.0.1")
    token = secrets.token_urlsafe(32)
    app = create_app(UiDependencies(
        settings=UiSettingsStore(DEFAULT_CONFIG_DIR / "ui.json"),
        picker=WindowsFilePicker(),
        profiles=ModelProfileStore(
            DEFAULT_CONFIG_DIR / "model-profiles.json",
            legacy_llm_path=DEFAULT_CONFIG_DIR / "llm-profiles.json",
            legacy_gemini_path=DEFAULT_CONFIG_DIR / "gemini-audio-profiles.json",
        ),
        worker=SubprocessWorkerAdapter(),
        startup_token=token,
        open_browser=open_browser,
        allowed_hosts={"127.0.0.1", "localhost"},
    ))
    url = f"http://{host}:{port}/?token={token}"
    if open_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    print(f"SubForge UI: {url}")
    uvicorn.run(app, host=host, port=port, access_log=False)
