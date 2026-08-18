from __future__ import annotations

from pathlib import Path

import httpx

from subforge.asr.model_manager import cached_models
from subforge.ui.profiles import LlmProfile


async def test_profile_connection(profile: LlmProfile) -> tuple[bool, str]:
    verify: bool | str = profile.verify_tls
    if profile.ca_bundle:
        verify = profile.ca_bundle
    try:
        async with httpx.AsyncClient(
            timeout=20,
            proxy=profile.proxy_url or None,
            verify=verify,
            trust_env=False,
        ) as client:
            response = await client.get(
                f"{profile.base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {profile.api_key}"},
            )
            response.raise_for_status()
        return True, "连接成功"
    except Exception as exc:
        from subforge.translate.llm_client import _describe_exception
        return False, _describe_exception(exc)


def check_model_configuration(
    model: str,
    models_dir: Path,
    direct_path: Path | None,
) -> tuple[bool, str]:
    if direct_path:
        if (direct_path / "model.bin").is_file() and (direct_path / "config.json").is_file():
            return True, f"直接模型目录可用：{direct_path}"
        return False, "直接模型目录缺少 model.bin 或 config.json"
    if model in cached_models(models_dir, [model]):
        return True, f"模型已缓存在：{models_dir}"
    return False, f"模型未缓存，运行时将下载到：{models_dir}"
