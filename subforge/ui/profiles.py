from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from uuid import uuid4


@dataclass
class LlmProfile:
    profile_id: str
    name: str
    base_url: str
    model: str
    api_key: str = ""
    proxy_url: str = ""
    verify_tls: bool = True
    ca_bundle: str = ""


def mask_secret(value: str) -> str:
    if not value:
        return "未配置"
    if len(value) < 12:
        return "已配置"
    return f"{value[:4]}{'•' * (len(value) - 8)}{value[-4:]}"


class LlmProfileStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _load(self) -> list[LlmProfile]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return [LlmProfile(**profile) for profile in data.get("profiles", [])]
        except (OSError, ValueError, json.JSONDecodeError, TypeError):
            return []

    def _save_all(self, profiles: list[LlmProfile]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"schema_version": 1, "profiles": [asdict(p) for p in profiles]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def save(
        self,
        name: str,
        base_url: str,
        model: str,
        api_key: str = "",
        profile_id: str | None = None,
        proxy_url: str = "",
        verify_tls: bool = True,
        ca_bundle: str = "",
    ) -> LlmProfile:
        if not name.strip() or not base_url.strip() or not model.strip():
            raise ValueError("name, base_url and model are required")
        profiles = self._load()
        existing = next((p for p in profiles if p.profile_id == profile_id), None)
        if existing:
            existing.name = name.strip()
            existing.base_url = base_url.strip()
            existing.model = model.strip()
            if api_key:
                existing.api_key = api_key
            existing.proxy_url = proxy_url.strip()
            existing.verify_tls = bool(verify_tls)
            existing.ca_bundle = ca_bundle.strip()
            profile = existing
        else:
            profile = LlmProfile(
                profile_id or uuid4().hex, name.strip(), base_url.strip(), model.strip(), api_key,
                proxy_url.strip(), bool(verify_tls), ca_bundle.strip(),
            )
            profiles.append(profile)
        self._save_all(profiles)
        return profile

    def resolve(self, profile_id: str) -> LlmProfile:
        profile = next((p for p in self._load() if p.profile_id == profile_id), None)
        if profile is None:
            raise KeyError(profile_id)
        if not profile.api_key and os.environ.get("LLM_API_KEY"):
            return replace(profile, api_key=os.environ["LLM_API_KEY"])
        return profile

    def list_public(self) -> list[dict]:
        return [
            {
                "profile_id": profile.profile_id,
                "name": profile.name,
                "base_url": profile.base_url,
                "model": profile.model,
                "proxy_url": profile.proxy_url,
                "verify_tls": profile.verify_tls,
                "ca_bundle": profile.ca_bundle,
                "api_key_masked": (
                    "已通过环境变量配置"
                    if not profile.api_key and os.environ.get("LLM_API_KEY")
                    else mask_secret(profile.api_key)
                ),
            }
            for profile in self._load()
        ]

    def delete_key(self, profile_id: str) -> None:
        profiles = self._load()
        profile = next((p for p in profiles if p.profile_id == profile_id), None)
        if profile is None:
            raise KeyError(profile_id)
        profile.api_key = ""
        self._save_all(profiles)

    def delete(self, profile_id: str) -> None:
        profiles = self._load()
        remaining = [p for p in profiles if p.profile_id != profile_id]
        if len(remaining) == len(profiles):
            raise KeyError(profile_id)
        self._save_all(remaining)
