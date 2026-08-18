from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse


class UiSettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _load(self) -> dict:
        if not self.path.exists():
            return {"schema_version": 1}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {"schema_version": 1}
        except (OSError, ValueError, json.JSONDecodeError):
            return {"schema_version": 1}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def get_active_library(self) -> Path | None:
        value = self._load().get("active_library")
        return Path(value).resolve() if value else None

    def set_active_library(self, root: Path) -> None:
        data = self._load()
        data["active_library"] = str(root.resolve())
        self._save(data)

    def get_deepgram_api_key(self) -> str:
        return os.environ.get("DEEPGRAM_API_KEY") or str(self._load().get("deepgram_api_key", ""))

    def deepgram_key_display(self) -> str:
        if os.environ.get("DEEPGRAM_API_KEY"):
            return "已通过环境变量配置"
        from subforge.ui.profiles import mask_secret
        return mask_secret(str(self._load().get("deepgram_api_key", "")))

    def set_deepgram_api_key(self, value: str) -> None:
        if not value:
            return
        data = self._load()
        data["deepgram_api_key"] = value
        self._save(data)

    def delete_deepgram_api_key(self) -> None:
        data = self._load()
        data.pop("deepgram_api_key", None)
        self._save(data)

    def get_models_dir(self) -> Path:
        value = self._load().get("models_dir")
        return Path(value).resolve() if value else (Path.home() / ".subforge" / "models")

    def set_models_dir(self, value: Path) -> None:
        value = value.resolve()
        value.mkdir(parents=True, exist_ok=True)
        data = self._load()
        data["models_dir"] = str(value)
        self._save(data)

    def get_direct_model_path(self, model: str) -> Path | None:
        value = self._load().get("direct_model_paths", {}).get(model)
        return Path(value).resolve() if value else None

    def set_direct_model_path(self, model: str, value: Path | None) -> None:
        if model not in {"medium", "large-v3"}:
            raise ValueError("unsupported model")
        data = self._load()
        paths = data.setdefault("direct_model_paths", {})
        if value is None:
            paths.pop(model, None)
        else:
            value = value.resolve()
            if not (value / "model.bin").is_file() or not (value / "config.json").is_file():
                raise ValueError("direct model directory must contain model.bin and config.json")
            paths[model] = str(value)
        self._save(data)

    def get_proxy_url(self) -> str:
        return str(self._load().get("proxy_url", ""))

    def set_proxy_url(self, value: str) -> None:
        value = value.strip()
        if value:
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https", "socks5"} or not parsed.hostname:
                raise ValueError("proxy URL must start with http://, https://, or socks5://")
        data = self._load()
        if value:
            data["proxy_url"] = value
        else:
            data.pop("proxy_url", None)
        self._save(data)

    def get_media_concurrency(self) -> int:
        value = int(self._load().get("media_concurrency", 1))
        return max(1, value)

    def set_media_concurrency(self, value: int) -> None:
        if value < 1:
            raise ValueError("media_concurrency must be at least 1")
        data = self._load()
        data["media_concurrency"] = value
        self._save(data)
