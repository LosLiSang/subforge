from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from math import ceil
from pathlib import Path
from typing import Any, Callable

import httpx

from subforge.config import Config
from subforge.translate.limiter import TranslationRequestLimiter

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_TIMEOUT = 120  # seconds


class LLMError(Exception):
    """Raised when the LLM API call fails after all retries."""


class LLMAuthError(LLMError):
    """Raised on 401 authentication errors (no retry)."""


def _mask_key(key: str) -> str:
    if len(key) < 8:
        return "*" * min(len(key), 4)
    return f"{key[:4]}...{key[-4:]}"


def _describe_exception(exception: Exception | None) -> str:
    if exception is None:
        return "unknown error"
    parts: list[str] = []
    current: BaseException | None = exception
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        detail = str(current).strip()
        label = type(current).__name__
        text = f"{label}: {detail}" if detail else label
        if text not in parts:
            parts.append(text)
        current = current.__cause__ or current.__context__
    return " <- ".join(parts)


def _is_retryable(exception: Exception) -> bool:
    """Determine if an exception should trigger a retry."""
    if isinstance(exception, LLMAuthError):
        return False
    if isinstance(exception, httpx.HTTPStatusError):
        status = exception.response.status_code
        if status == 401:
            return False
        return status in (429, 502, 503, 504)
    if isinstance(exception, httpx.TimeoutException):
        return True
    if isinstance(exception, httpx.NetworkError):
        return True
    return False


def _get_retry_after(exception: Exception) -> int | None:
    """Extract Retry-After seconds from either delta-seconds or an HTTP date."""
    if not isinstance(exception, httpx.HTTPStatusError):
        return None
    value = exception.response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0, int(value))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=UTC)
            return max(0, ceil((retry_at - datetime.now(UTC)).total_seconds()))
        except (TypeError, ValueError, OverflowError):
            return None


def _build_body(messages: list[dict[str, str]], config: Config) -> dict[str, Any]:
    return {
        "model": config.llm_model,
        "messages": messages,
        "temperature": 0.3,
        # 推理模型（reasoning）会把 token 花在 reasoning_content 上，预算太小会
        # 吃光 max_tokens 导致 content 为空；给足预算避免空翻译。
        "max_tokens": 16384,
    }


async def translate_batch(
    messages: list[dict[str, str]],
    config: Config,
    client: httpx.AsyncClient | None = None,
    activity_callback: Callable[[str], None] | None = None,
) -> str:
    """Send a batch of messages to the LLM and return the response text.

    Args:
        messages: List of message dicts in OpenAI chat format.
        config: Application configuration.
        client: Optional pre-configured httpx.AsyncClient.

    Returns:
        The LLM's response text content.

    Raises:
        LLMAuthError: On 401 (immediate, no retry).
        LLMError: After exhausting all retries.
    """
    close_client = False
    if client is None:
        verify: bool | str = config.llm_verify_tls
        if config.llm_ca_bundle:
            verify = str(Path(config.llm_ca_bundle))
        client = httpx.AsyncClient(
            timeout=_TIMEOUT,
            proxy=config.llm_proxy_url or None,
            verify=verify,
            trust_env=False,  # LLM 网络与下载代理解耦：env 代理不得劫持翻译请求
        )
        close_client = True

    masked_key = _mask_key(config.llm_api_key)
    logger.info("LLM: calling %s model=%s key=%s",
                 config.llm_base_url, config.llm_model, masked_key)

    headers = {
        "Authorization": f"Bearer {config.llm_api_key}",
        "Content-Type": "application/json",
    }
    body = _build_body(messages, config)
    url = f"{config.llm_base_url.rstrip('/')}/chat/completions"

    last_exception: Exception | None = None
    request_limiter = TranslationRequestLimiter(
        config.translation_limiter_dir,
        config.translation_global_workers,
    )

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            if activity_callback:
                activity_callback(f"Calling LLM (attempt {attempt}/{_MAX_RETRIES})")
            async with request_limiter.slot():
                response = await client.post(url, json=body, headers=headers)
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            # 并发下服务端可能返回空 content（推理截断/瞬时异常，HTTP 仍 200）。
            # 空 content 当作可重试失败，绝不能静默当作成功返回。
            if content is None or not str(content).strip():
                last_exception = LLMError(
                    "LLM returned empty content (finish_reason may be 'length')"
                )
                if attempt < _MAX_RETRIES:
                    wait = 2 ** (attempt - 1)
                    logger.warning(
                        "LLM: empty content on attempt %d/%d, waiting %ds...",
                        attempt, _MAX_RETRIES, wait,
                    )
                    if activity_callback:
                        activity_callback(
                            f"等待重试 · 空响应 · 请求 {attempt}/{_MAX_RETRIES} · {wait}秒后重试"
                        )
                    await asyncio.sleep(wait)
                continue
            content = str(content)
            if close_client:
                await client.aclose()
            return content

        except httpx.HTTPStatusError as e:
            last_exception = e
            status = e.response.status_code
            if status == 401:
                if close_client:
                    await client.aclose()
                raise LLMAuthError(
                    f"Authentication failed (401). Check your API key. "
                    f"Key used: {masked_key}"
                ) from e
            if not _is_retryable(e):
                if close_client:
                    await client.aclose()
                raise LLMError(f"Non-retryable HTTP error: {status}") from e
            if attempt < _MAX_RETRIES:
                retry_after = _get_retry_after(e)
                wait = retry_after if retry_after is not None else (2 ** (attempt - 1))
                logger.warning("LLM: HTTP %d on attempt %d/%d, waiting %ds...",
                               status, attempt, _MAX_RETRIES, wait)
                if activity_callback:
                    activity_callback(
                        f"等待重试 · HTTP {status} · 请求 {attempt}/{_MAX_RETRIES} · {wait}秒后重试"
                    )
                await asyncio.sleep(wait)

        except (httpx.TimeoutException, httpx.NetworkError) as e:
            last_exception = e
            if attempt < _MAX_RETRIES:
                wait = 2 ** (attempt - 1)
                logger.warning("LLM: %s on attempt %d/%d, waiting %ds...",
                               type(e).__name__, attempt, _MAX_RETRIES, wait)
                if activity_callback:
                    activity_callback(
                        f"等待重试 · {_describe_exception(e)} · 请求 {attempt}/{_MAX_RETRIES} · {wait}秒后重试"
                    )
                await asyncio.sleep(wait)

    if close_client:
        await client.aclose()
    raise LLMError(
        f"LLM call failed after {_MAX_RETRIES} attempts. "
        f"Last error: {_describe_exception(last_exception)}"
    ) from last_exception
