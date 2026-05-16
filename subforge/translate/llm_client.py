from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from subforge.config import Config

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


def _is_retryable(exception: Exception) -> bool:
    """Determine if an exception should trigger a retry."""
    if isinstance(exception, LLMAuthError):
        return False
    if isinstance(exception, httpx.HTTPStatusError):
        status = exception.response.status_code
        if status == 401:
            return False
        return status in (429, 500, 502, 503, 504) or status >= 500
    if isinstance(exception, httpx.TimeoutException):
        return True
    if isinstance(exception, httpx.NetworkError):
        return True
    return False


def _get_retry_after(exception: Exception) -> int | None:
    """Extract Retry-After header value in seconds from 429 response."""
    if isinstance(exception, httpx.HTTPStatusError):
        val = exception.response.headers.get("Retry-After")
        if val is not None:
            try:
                return int(val)
            except ValueError:
                pass
    return None


def _build_body(messages: list[dict[str, str]], config: Config) -> dict[str, Any]:
    return {
        "model": config.llm_model,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 4096,
    }


async def translate_batch(
    messages: list[dict[str, str]],
    config: Config,
    client: httpx.AsyncClient | None = None,
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
        client = httpx.AsyncClient(timeout=_TIMEOUT)
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

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = await client.post(url, json=body, headers=headers)
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
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
            retry_after = _get_retry_after(e)
            wait = retry_after if retry_after else (2 ** (attempt - 1))
            logger.warning("LLM: HTTP %d on attempt %d/%d, waiting %ds...",
                           status, attempt, _MAX_RETRIES, wait)
            time.sleep(wait)

        except (httpx.TimeoutException, httpx.NetworkError) as e:
            last_exception = e
            wait = 2 ** (attempt - 1)
            logger.warning("LLM: %s on attempt %d/%d, waiting %ds...",
                           type(e).__name__, attempt, _MAX_RETRIES, wait)
            time.sleep(wait)

    if close_client:
        await client.aclose()
    raise LLMError(
        f"LLM call failed after {_MAX_RETRIES} retries. "
        f"Last error: {last_exception}"
    ) from last_exception
