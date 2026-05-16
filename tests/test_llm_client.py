from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from subforge.config import Config
from subforge.translate.llm_client import (
    LLMAuthError,
    LLMError,
    _mask_key,
    translate_batch,
)


class TestMaskKey:
    def test_short_key(self):
        assert _mask_key("abc") == "***"

    def test_exact_eight(self):
        assert _mask_key("12345678") == "1234...5678"

    def test_long_key(self):
        assert _mask_key("sk-abcdefghijklmnop") == "sk-a...mnop"

    def test_empty(self):
        assert _mask_key("") == ""


@pytest.fixture
def config():
    return Config(
        llm_api_key="sk-test12345678",
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
    )


@pytest.fixture
def messages():
    return [
        {"role": "system", "content": "You are a translator."},
        {"role": "user", "content": "Translate: こんにちは"},
    ]


def _ok_response(content: str) -> MagicMock:
    """Create a mock 200 OK response with given content."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = {"choices": [{"message": {"content": content}}]}
    resp.raise_for_status = MagicMock()  # callable, no side effect
    return resp


def _error_response(status: int, headers: dict | None = None) -> MagicMock:
    """Create a mock error response that raises on raise_for_status()."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.headers = headers or {}
    resp.json.return_value = {"error": "error"}
    exc = httpx.HTTPStatusError("error", request=MagicMock(), response=resp)
    resp.raise_for_status.side_effect = exc
    return resp


class TestTranslateBatch:
    async def test_success(self, config, messages):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.return_value = _ok_response("你好")

        result = await translate_batch(messages, config, client=mock_client)

        assert result == "你好"
        mock_client.post.assert_called_once()

    async def test_auth_error_no_retry(self, config, messages):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        error_resp = _error_response(401)
        exc = httpx.HTTPStatusError("unauthorized", request=MagicMock(), response=error_resp)
        mock_client.post.return_value = error_resp

        with pytest.raises(LLMAuthError, match="401"):
            await translate_batch(messages, config, client=mock_client)

        assert mock_client.post.call_count == 1

    async def test_rate_limit_with_retry(self, config, messages):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        error_resp = _error_response(429, headers={"Retry-After": "0"})
        error_exc = httpx.HTTPStatusError("rate limited", request=MagicMock(), response=error_resp)
        ok_resp = _ok_response("hello")
        mock_client.post.side_effect = [error_exc, ok_resp]

        result = await translate_batch(messages, config, client=mock_client)

        assert result == "hello"
        assert mock_client.post.call_count == 2

    async def test_timeout_with_retry(self, config, messages):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.side_effect = [
            httpx.TimeoutException("timeout"),
            _ok_response("ok"),
        ]

        result = await translate_batch(messages, config, client=mock_client)

        assert result == "ok"
        assert mock_client.post.call_count == 2

    async def test_exhausted_retries(self, config, messages):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.side_effect = httpx.TimeoutException("timeout")

        with pytest.raises(LLMError, match="3 retries"):
            await translate_batch(messages, config, client=mock_client)

        assert mock_client.post.call_count == 3

    async def test_network_error_retry(self, config, messages):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.side_effect = [
            httpx.NetworkError("connection reset"),
            _ok_response("ok"),
        ]

        result = await translate_batch(messages, config, client=mock_client)

        assert result == "ok"
        assert mock_client.post.call_count == 2
