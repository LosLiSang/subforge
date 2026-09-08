"""统一模型 Profile：一个 Profile 可同时承担 ASR / 翻译 / 合并等能力。

历史上翻译配置（``LlmProfile``）与 Gemini 音频配置（``GeminiAudioProfile``）是
两份独立存储。用户实测 Gemini 类模型既能当 ASR 也能当翻译，因此这里把两者合并
为带能力标记的单一 Profile：

- ``transcribe``：可作为 ASR（音频 → 文本）
- ``translate``：可作为翻译模型（文本 → 文本）
- ``merge``：可作为分片结果的文本层合并模型

UI 的 ASR / 翻译 / 合并下拉按能力过滤同一份 Profile 集合；旧的
``llm-profiles.json`` 与 ``gemini-audio-profiles.json`` 在首次加载时自动迁移。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from uuid import uuid4

from subforge.ui.profiles import mask_secret

CAPABILITIES = ("transcribe", "translate", "merge")
PROTOCOLS = ("openai_compatible", "google_native")


def _normalize_capabilities(value) -> list[str]:
    if isinstance(value, str):
        raw = [part.strip() for part in value.split(",")]
    elif isinstance(value, (list, tuple, set)):
        raw = [str(part).strip() for part in value]
    else:
        raw = []
    return [capability for capability in CAPABILITIES if capability in raw]


@dataclass
class ModelProfile:
    profile_id: str
    name: str
    base_url: str
    model: str
    api_key: str = ""
    protocol: str = "openai_compatible"
    capabilities: list[str] = field(default_factory=lambda: ["translate"])
    # 单个 ASR 请求允许的最大音频时长（秒），超过即分片。
    max_request_seconds: int = 60
    temperature: float = 0.0
    transcribe_prompt: str = ""
    bilingual_prompt: str = ""
    translate_prompt: str = ""
    merge_prompt: str = ""
    proxy_url: str = ""
    verify_tls: bool = True
    ca_bundle: str = ""

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities


class ModelProfileStore:
    """单一模型 Profile 存储，支持从旧的两份存储自动迁移。"""

    def __init__(
        self,
        path: Path,
        *,
        legacy_llm_path: Path | None = None,
        legacy_gemini_path: Path | None = None,
    ) -> None:
        self.path = path
        self._legacy_llm_path = legacy_llm_path
        self._legacy_gemini_path = legacy_gemini_path

    # ── 读写 ────────────────────────────────────────────────────────────
    def _load(self) -> list[ModelProfile]:
        if not self.path.exists():
            migrated = self._migrate_legacy()
            if migrated:
                self._save_all(migrated)
            return migrated
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return []
        known = {item.name for item in fields(ModelProfile)}
        profiles: list[ModelProfile] = []
        for item in data.get("profiles", []):
            if not isinstance(item, dict):
                continue
            try:
                profiles.append(ModelProfile(**{k: v for k, v in item.items() if k in known}))
            except TypeError:
                continue
        for profile in profiles:
            profile.capabilities = _normalize_capabilities(profile.capabilities)
        return profiles

    def _save_all(self, profiles: list[ModelProfile]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {"schema_version": 1, "profiles": [asdict(profile) for profile in profiles]},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)

    # ── 迁移 ────────────────────────────────────────────────────────────
    def _migrate_legacy(self) -> list[ModelProfile]:
        """把旧的翻译配置与 Gemini 音频配置合并为统一 Profile。"""
        migrated: list[ModelProfile] = []
        seen: set[str] = set()

        if self._legacy_llm_path and self._legacy_llm_path.exists():
            for item in self._read_json_profiles(self._legacy_llm_path):
                profile_id = str(item.get("profile_id") or uuid4().hex)
                if profile_id in seen:
                    continue
                seen.add(profile_id)
                migrated.append(ModelProfile(
                    profile_id=profile_id,
                    name=str(item.get("name", "")).strip() or profile_id,
                    base_url=str(item.get("base_url", "")).strip(),
                    model=str(item.get("model", "")).strip(),
                    api_key=str(item.get("api_key", "")),
                    protocol="openai_compatible",
                    capabilities=["translate"],
                    proxy_url=str(item.get("proxy_url", "")),
                    verify_tls=bool(item.get("verify_tls", True)),
                    ca_bundle=str(item.get("ca_bundle", "")),
                ))

        if self._legacy_gemini_path and self._legacy_gemini_path.exists():
            for item in self._read_json_profiles(self._legacy_gemini_path):
                profile_id = str(item.get("profile_id") or uuid4().hex)
                if profile_id in seen:
                    continue
                seen.add(profile_id)
                protocol = str(item.get("protocol", "google_native"))
                migrated.append(ModelProfile(
                    profile_id=profile_id,
                    name=str(item.get("name", "")).strip() or profile_id,
                    base_url=str(item.get("base_url", "")).strip(),
                    model=str(item.get("model", "")).strip(),
                    api_key=str(item.get("api_key", "")),
                    protocol=protocol if protocol in PROTOCOLS else "google_native",
                    capabilities=["transcribe", "translate"],
                    max_request_seconds=int(item.get("max_segment_seconds", 60) or 60),
                    temperature=float(item.get("temperature", 0.0) or 0.0),
                    transcribe_prompt=str(item.get("transcribe_prompt", "")),
                    bilingual_prompt=str(item.get("bilingual_prompt", "")),
                    proxy_url=str(item.get("proxy_url", "")),
                    verify_tls=bool(item.get("verify_tls", True)),
                    ca_bundle=str(item.get("ca_bundle", "")),
                ))
        return migrated

    @staticmethod
    def _read_json_profiles(path: Path) -> list[dict]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return []
        profiles = data.get("profiles", []) if isinstance(data, dict) else []
        return [item for item in profiles if isinstance(item, dict)]

    # ── 公共 API ────────────────────────────────────────────────────────
    def save(
        self,
        name: str,
        base_url: str,
        model: str,
        api_key: str = "",
        *,
        profile_id: str | None = None,
        protocol: str = "openai_compatible",
        capabilities=None,
        max_request_seconds: int = 60,
        temperature: float = 0.0,
        transcribe_prompt: str = "",
        bilingual_prompt: str = "",
        translate_prompt: str = "",
        merge_prompt: str = "",
        proxy_url: str = "",
        verify_tls: bool = True,
        ca_bundle: str = "",
    ) -> ModelProfile:
        if not name.strip() or not base_url.strip() or not model.strip():
            raise ValueError("name, base_url and model are required")
        if protocol not in PROTOCOLS:
            raise ValueError("unsupported model protocol")
        normalized_caps = _normalize_capabilities(capabilities) if capabilities is not None else ["translate"]
        if not normalized_caps:
            raise ValueError("至少选择一项能力（转写 / 翻译 / 合并）")
        if int(max_request_seconds) < 1:
            raise ValueError("max_request_seconds must be at least 1")
        profiles = self._load()
        existing = next((profile for profile in profiles if profile.profile_id == profile_id), None)
        if existing is None:
            existing = ModelProfile(
                profile_id or uuid4().hex, name.strip(), base_url.rstrip("/"), model.strip(), api_key,
            )
            profiles.append(existing)
        existing.name = name.strip()
        existing.base_url = base_url.rstrip("/")
        existing.model = model.strip()
        if api_key:
            existing.api_key = api_key
        existing.protocol = protocol
        existing.capabilities = normalized_caps
        existing.max_request_seconds = int(max_request_seconds)
        try:
            existing.temperature = max(0.0, min(2.0, float(temperature)))
        except (TypeError, ValueError):
            existing.temperature = 0.0
        existing.transcribe_prompt = transcribe_prompt.strip()
        existing.bilingual_prompt = bilingual_prompt.strip()
        existing.translate_prompt = translate_prompt.strip()
        existing.merge_prompt = merge_prompt.strip()
        existing.proxy_url = proxy_url.strip()
        existing.verify_tls = bool(verify_tls)
        existing.ca_bundle = ca_bundle.strip()
        self._save_all(profiles)
        return existing

    def copy(self, source_profile_id: str, *, name: str, base_url: str, model: str, **overrides) -> ModelProfile:
        source = self.resolve(source_profile_id)
        return self.save(
            profile_id=None,
            name=name,
            base_url=base_url,
            model=model,
            api_key=overrides.pop("api_key", "") or source.api_key,
            protocol=overrides.pop("protocol", source.protocol),
            capabilities=overrides.pop("capabilities", list(source.capabilities)),
            max_request_seconds=overrides.pop("max_request_seconds", source.max_request_seconds),
            temperature=overrides.pop("temperature", source.temperature),
            transcribe_prompt=overrides.pop("transcribe_prompt", source.transcribe_prompt),
            bilingual_prompt=overrides.pop("bilingual_prompt", source.bilingual_prompt),
            translate_prompt=overrides.pop("translate_prompt", source.translate_prompt),
            merge_prompt=overrides.pop("merge_prompt", source.merge_prompt),
            proxy_url=overrides.pop("proxy_url", source.proxy_url),
            verify_tls=overrides.pop("verify_tls", source.verify_tls),
            ca_bundle=overrides.pop("ca_bundle", source.ca_bundle),
        )

    def resolve(self, profile_id: str) -> ModelProfile:
        profile = next((profile for profile in self._load() if profile.profile_id == profile_id), None)
        if profile is None:
            raise KeyError(profile_id)
        if not profile.api_key:
            env_key = os.environ.get("GEMINI_API_KEY") if profile.protocol == "google_native" else None
            env_key = env_key or os.environ.get("LLM_API_KEY")
            if env_key:
                profile = replace(profile, api_key=env_key)
        return profile

    def list_public(self) -> list[dict]:
        result = []
        for profile in self._load():
            item = asdict(profile)
            item.pop("api_key", None)
            if not profile.api_key:
                if profile.protocol == "google_native" and os.environ.get("GEMINI_API_KEY"):
                    item["api_key_masked"] = "已通过环境变量配置"
                elif os.environ.get("LLM_API_KEY"):
                    item["api_key_masked"] = "已通过环境变量配置"
                else:
                    item["api_key_masked"] = mask_secret(profile.api_key)
            else:
                item["api_key_masked"] = mask_secret(profile.api_key)
            result.append(item)
        return result

    def list_for(self, capability: str) -> list[dict]:
        """按能力过滤，供 ASR / 翻译 / 合并下拉使用。"""
        return [item for item in self.list_public() if capability in item.get("capabilities", [])]

    def delete_key(self, profile_id: str) -> None:
        profiles = self._load()
        profile = next((profile for profile in profiles if profile.profile_id == profile_id), None)
        if profile is None:
            raise KeyError(profile_id)
        profile.api_key = ""
        self._save_all(profiles)

    def delete(self, profile_id: str) -> None:
        profiles = self._load()
        remaining = [profile for profile in profiles if profile.profile_id != profile_id]
        if len(remaining) == len(profiles):
            raise KeyError(profile_id)
        self._save_all(remaining)
