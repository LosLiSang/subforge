from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from unittest.mock import AsyncMock, MagicMock, patch

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

    async def test_connect_error_reports_type_and_underlying_ssl_reason(self, config, messages):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        cause = RuntimeError("certificate verify failed")
        error = httpx.ConnectError("", request=MagicMock())
        error.__cause__ = cause
        mock_client.post.side_effect = error

        with pytest.raises(LLMError) as captured:
            await translate_batch(messages, config, client=mock_client)

        assert "ConnectError" in str(captured.value)
        assert "certificate verify failed" in str(captured.value)

    async def test_exhausted_retries(self, config, messages):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.side_effect = httpx.TimeoutException("timeout")

        with patch("subforge.translate.llm_client.asyncio.sleep", new=AsyncMock()) as sleep:
            with pytest.raises(LLMError, match="3 attempts"):
                await translate_batch(messages, config, client=mock_client)

        assert mock_client.post.call_count == 3
        assert sleep.await_count == 2

    async def test_http_500_is_not_retried(self, config, messages):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.return_value = _error_response(500)

        with pytest.raises(LLMError, match="Non-retryable HTTP error: 500"):
            await translate_batch(messages, config, client=mock_client)

        assert mock_client.post.call_count == 1

    async def test_retry_after_http_date_is_respected(self, config, messages):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        retry_at = format_datetime(datetime.now(UTC) + timedelta(seconds=2), usegmt=True)
        mock_client.post.side_effect = [
            _error_response(429, headers={"Retry-After": retry_at}),
            _ok_response("ok"),
        ]
        activity = MagicMock()

        with patch("subforge.translate.llm_client.asyncio.sleep", new=AsyncMock()) as sleep:
            result = await translate_batch(messages, config, client=mock_client, activity_callback=activity)

        assert result == "ok"
        waited = sleep.await_args.args[0]
        assert 0 <= waited <= 2
        assert any("1/3" in call.args[0] and "HTTP 429" in call.args[0] for call in activity.call_args_list)

    async def test_network_error_retry(self, config, messages):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.side_effect = [
            httpx.NetworkError("connection reset"),
            _ok_response("ok"),
        ]

        result = await translate_batch(messages, config, client=mock_client)

        assert result == "ok"
        assert mock_client.post.call_count == 2


class TestEnvProxyIsolation:
    async def test_client_ignores_environment_proxies(self, config, messages, monkeypatch):
        """LLM 端点网络必须与下载代理解耦：即使进程 env 里有代理变量，
        未配置 llm_proxy_url 的翻译请求也必须直连（trust_env=False）。"""
        monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
        monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
        monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:9")

        with patch("subforge.translate.llm_client.httpx.AsyncClient", wraps=httpx.AsyncClient) as spy:
            mock_client = MagicMock()
            mock_client.post = AsyncMock(return_value=_ok_response("你好"))
            mock_client.aclose = AsyncMock()
            spy.return_value = mock_client
            await translate_batch(messages, config)

        # AsyncClient 必须以 trust_env=False 构造
        spy.assert_called_once()
        kwargs = spy.call_args.kwargs
        assert kwargs.get("trust_env") is False
        assert kwargs.get("proxy") is None


class TestEmptyContentRetry:
    async def test_empty_content_retries_then_succeeds(self, config, messages):
        """并发下服务端可能返回空 content（推理截断/瞬时异常）：必须重试而非当作成功。"""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.side_effect = [
            _ok_response(""),          # 第一次空 content
            _ok_response("你好"),      # 第二次成功
        ]

        result = await translate_batch(messages, config, client=mock_client)

        assert result == "你好"
        assert mock_client.post.call_count == 2

    async def test_all_empty_content_exhausts_retries(self, config, messages):
        """连续空 content 3 次后必须报错，不能返回空串让上层静默缓存。"""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.return_value = _ok_response("")

        with pytest.raises(LLMError, match="empty"):
            await translate_batch(messages, config, client=mock_client)

        assert mock_client.post.call_count == 3
