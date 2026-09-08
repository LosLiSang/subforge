from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from subforge.gemini_audio import (
    GeminiAudioAdapter,
    GeminiAudioProfile,
    GeminiAudioProfileStore,
    GeminiAudioTransport,
    GoogleGeminiTransport,
    OpenAICompatibleAudioTransport,
)
from subforge.models import SubtitleEntry
from subforge.segment_processing import ExtractedAudio, SegmentRequest


class _Upstream:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __enter__(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("content-length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                owner.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
                status, payload = owner.responses.pop(0)
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, _format, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        return self

    def __exit__(self, *_args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def test_profile_store_keeps_gemini_audio_separate_and_masks_key(tmp_path, monkeypatch):
    store = GeminiAudioProfileStore(tmp_path / "gemini-audio.json")
    profile = store.save(
        name="内网 Gemini",
        protocol="openai_compatible",
        base_url="https://example.invalid/v1",
        model="gemini-3.8-flash-high",
        api_key="secret-value-12345",
        default_processing_mode="bilingual_once",
        max_segment_seconds=90,
        verify_tls=False,
    )

    public = store.list_public()[0]
    assert public["profile_id"] == profile.profile_id
    assert public["api_key_masked"].startswith("secr")
    assert "secret-value-12345" not in json.dumps(public)
    assert store.resolve(profile.profile_id).protocol == "openai_compatible"

    monkeypatch.setenv("GEMINI_API_KEY", "environment-secret")
    store.delete_key(profile.profile_id)
    assert store.resolve(profile.profile_id).api_key == "environment-secret"


@pytest.mark.asyncio
async def test_google_transport_sends_inline_audio_to_generate_content():
    with _Upstream([(200, {"candidates": [{"content": {"parts": [{"text": "こんにちは"}]}}]})]) as upstream:
        profile = GeminiAudioProfile(
            "id", "Google", "google_native", upstream.base_url,
            "gemini-3.8-flash-high", "key-value",
        )
        transport = GoogleGeminiTransport(profile)
        result = await transport.generate(b"wave-bytes", "audio/wav", "逐字转写")

    assert result == "こんにちは"
    request = upstream.requests[0]
    assert request["path"] == "/v1beta/models/gemini-3.8-flash-high:generateContent"
    assert request["headers"]["x-goog-api-key"] == "key-value"
    part = request["body"]["contents"][0]["parts"][1]["inline_data"]
    assert part["mime_type"] == "audio/wav"
    assert part["data"]


@pytest.mark.asyncio
async def test_openai_compatible_transport_sends_input_audio_and_retries_empty():
    responses = [
        (200, {"choices": [{"message": {"content": ""}}]}),
        (200, {"choices": [{"message": {"content": "转写成功"}}]}),
    ]
    with _Upstream(responses) as upstream:
        profile = GeminiAudioProfile(
            "id", "Gateway", "openai_compatible", upstream.base_url + "/v1",
            "gemini-3.8-flash-high", "gateway-key",
        )
        transport = OpenAICompatibleAudioTransport(profile, retry_delays=(0, 0))
        result = await transport.generate(b"wave-bytes", "audio/wav", "逐字转写")

    assert result == "转写成功"
    assert len(upstream.requests) == 2
    request = upstream.requests[-1]
    assert request["path"] == "/v1/chat/completions"
    assert request["headers"]["Authorization"] == "Bearer gateway-key"
    content = request["body"]["messages"][0]["content"]
    assert content[1]["type"] == "input_audio"
    assert content[1]["input_audio"]["format"] == "wav"


class _FakeTransport(GeminiAudioTransport):
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def generate(self, audio, mime_type, prompt):
        self.calls.append((audio, mime_type, prompt))
        return self.response


@pytest.mark.asyncio
async def test_gemini_adapter_supports_bilingual_and_two_stage_modes(tmp_path):
    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"audio")

    def extractor(_request):
        return ExtractedAudio(clip, 8.0, 14.0, temporary=False)

    bilingual = _FakeTransport('{"source_text":"こんにちは","target_text":"你好"}')
    profile = GeminiAudioProfile(
        "id", "Gemini", "google_native", "https://example.invalid",
        "gemini-3.8-flash-high", "key", default_processing_mode="bilingual_once",
    )
    adapter = GeminiAudioAdapter(profile, bilingual, extractor=extractor)
    candidate = await adapter.process(SegmentRequest(
        tmp_path / "audio.m4a", 10.0, 12.0, processing_mode="bilingual_once"
    ))
    assert candidate.source_entries == [SubtitleEntry(1, 10.0, 12.0, "こんにちは")]
    assert candidate.target_entries == [SubtitleEntry(1, 10.0, 12.0, "你好")]

    source_only = _FakeTransport("こんにちは")

    async def translate(entries, _source, _target):
        return [SubtitleEntry(1, entries[0].start, entries[0].end, "你好")]

    adapter = GeminiAudioAdapter(profile, source_only, extractor=extractor, translate_fn=translate)
    candidate = await adapter.process(SegmentRequest(
        tmp_path / "audio.m4a", 10.0, 12.0, processing_mode="transcribe_then_translate"
    ))
    assert candidate.source_entries[0].text == "こんにちは"
    assert candidate.target_entries[0].text == "你好"


@pytest.mark.asyncio
async def test_gemini_adapter_rejects_segments_over_profile_limit(tmp_path):
    profile = GeminiAudioProfile(
        "id", "Gemini", "google_native", "https://example.invalid",
        "gemini-3.8-flash-high", "key", max_segment_seconds=60,
    )
    transport = _FakeTransport("不会调用")
    adapter = GeminiAudioAdapter(profile, transport)
    with pytest.raises(ValueError, match="60 秒"):
        await adapter.process(SegmentRequest(tmp_path / "audio.m4a", 0.0, 61.0))
    assert transport.calls == []
