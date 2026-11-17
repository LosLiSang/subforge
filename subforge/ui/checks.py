from __future__ import annotations

import httpx

from subforge.ui.model_profiles import ModelProfile


async def test_profile_connection(profile: ModelProfile) -> tuple[bool, str]:
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
