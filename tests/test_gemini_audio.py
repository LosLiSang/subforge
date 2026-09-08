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


def test_profile_store_allows_long_segments_without_hard_cap(tmp_path, monkeypatch):
    store = GeminiAudioProfileStore(tmp_path / "gemini-audio.json")
    profile = store.save(
        name="内网 Gemini",
        protocol="openai_compatible",
        base_url="https://example.invalid/v1",
        model="gemini-3.8-flash-high",
        api_key="secret-value-12345",
        default_processing_mode="bilingual_once",
        max_segment_seconds=1800,
        verify_tls=False,
    )
    assert profile.max_segment_seconds == 1800

    public = store.list_public()[0]
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
async def test_gemini_adapter_splits_long_segments_by_silence(tmp_path):
    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"audio")

    def extractor(_request):
        return ExtractedAudio(clip, 10.0, 70.0, temporary=False)

    calls = []

    class ChunkTransport(GeminiAudioTransport):
        async def generate(self, audio, mime_type, prompt):
            calls.append(audio)
            return f'{{"source_text":"片段{len(calls)}","target_text":"译文{len(calls)}"}}'

    regions = [(0.0, 30.0), (30.5, 60.0)]  # clip 相对：两段语音，中间 0.5s 静音
    profile = GeminiAudioProfile(
        "id", "Gemini", "google_native", "https://example.invalid",
        "gemini-3.8-flash-high", "key",
        default_processing_mode="bilingual_once", max_segment_seconds=25,
    )
    adapter = GeminiAudioAdapter(
        profile, ChunkTransport(), extractor=extractor,
        speech_regions=lambda _path, _total: regions,
        chunk_cutter=lambda _path, _start, _end: b"chunk",
    )
    candidate = await adapter.process(SegmentRequest(
        tmp_path / "audio.m4a", 10.0, 70.0, processing_mode="bilingual_once"
    ))

    assert len(calls) == 4  # 两段语音各 30s/29.5s，均超过 25s → 各均匀切两块
    assert [e.text for e in candidate.source_entries] == ["片段1", "片段2", "片段3", "片段4"]
    # 绝对时间 = clip 起点 + chunk 相对区间；跨静音处不合并，保持语音边界
    assert candidate.source_entries[0].start == 10.0
    assert candidate.source_entries[0].end == 25.0
    assert candidate.source_entries[1].end == 40.0
    assert candidate.source_entries[2].start == 40.5
    assert candidate.source_entries[3].end == 70.0
    assert any("切分" in warning for warning in candidate.warnings)


@pytest.mark.asyncio
async def test_gemini_adapter_falls_back_to_single_chunk_when_detection_fails(tmp_path):
    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"audio")

    def extractor(_request):
        return ExtractedAudio(clip, 10.0, 70.0, temporary=False)

    calls = []

    class ChunkTransport(GeminiAudioTransport):
        async def generate(self, audio, mime_type, prompt):
            calls.append(audio)
            return '{"source_text":"整段","target_text":"整译"}'

    def broken_detector(_path, _total):
        raise RuntimeError("silencedetect failed")

    profile = GeminiAudioProfile(
        "id", "Gemini", "google_native", "https://example.invalid",
        "gemini-3.8-flash-high", "key", max_segment_seconds=25,
    )
    adapter = GeminiAudioAdapter(
        profile, ChunkTransport(), extractor=extractor,
        speech_regions=broken_detector,
    )
    candidate = await adapter.process(SegmentRequest(
        tmp_path / "audio.m4a", 10.0, 70.0, processing_mode="bilingual_once"
    ))
    assert len(calls) == 1
    assert candidate.source_entries == [SubtitleEntry(1, 10.0, 70.0, "整段")]
    assert any("检测失败" in warning for warning in candidate.warnings)


@pytest.mark.asyncio
async def test_gemini_segmented_output_splits_entries_and_validates_timestamps(tmp_path):
    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"audio")

    def extractor(_request):
        return ExtractedAudio(clip, 10.0, 40.0, temporary=False)

    structured = (
        '{"segments":['
        '{"start":0,"end":10,"source_text":"第一句","target_text":"译文一"},'
        '{"start":10,"end":20,"source_text":"第二句","target_text":"译文二"},'
        '{"start":25,"end":30,"source_text":"第三句","target_text":"译文三"}]}'
    )
    profile = GeminiAudioProfile(
        "id", "Gemini", "google_native", "https://example.invalid",
        "gemini-3.8-flash-high", "key",
        default_processing_mode="bilingual_once", max_segment_seconds=60,
    )
    adapter = GeminiAudioAdapter(profile, _FakeTransport(structured), extractor=extractor)
    candidate = await adapter.process(SegmentRequest(
        tmp_path / "audio.m4a", 12.0, 38.0, processing_mode="bilingual_once"
    ))

    # 绝对时间 = clip 起点 10 + 模型相对时间；钳制到目标选区 12–38
    assert [(e.start, e.end, e.text) for e in candidate.source_entries] == [
        (12.0, 20.0, "第一句"),
        (20.0, 30.0, "第二句"),
        (35.0, 38.0, "第三句"),  # 25+10=35 起
    ]
    assert candidate.target_entries[-1].text == "译文三"
    assert any("切分为 3 条" in w for w in candidate.warnings)

    # 乱序时间戳 → 回退为按文本长度比例分配
    scrambled = (
        '{"segments":['
        '{"start":30,"end":5,"source_text":"甲甲甲甲甲","target_text":"译一"},'
        '{"start":8,"end":3,"source_text":"乙乙乙乙乙","target_text":"译二"}]}'
    )
    adapter = GeminiAudioAdapter(profile, _FakeTransport(scrambled), extractor=extractor)
    candidate = await adapter.process(SegmentRequest(
        tmp_path / "audio.m4a", 10.0, 40.0, processing_mode="bilingual_once"
    ))
    assert [e.text for e in candidate.source_entries] == ["甲甲甲甲甲", "乙乙乙乙乙"]
    assert candidate.source_entries[0].start == 10.0
    assert candidate.source_entries[0].end == 25.0  # 等长 → 对半分
    assert candidate.source_entries[1].end == 40.0


@pytest.mark.asyncio
async def test_profile_temperature_and_custom_prompt_reach_transport(tmp_path):
    """Profile 可配置温度与提示词模板；透传到请求体。"""
    with _Upstream([(200, {"candidates": [{"content": {"parts": [{"text": '{"segments":[{"start":0,"end":1,"text":"晴"}]}'}]}}]})]) as upstream:
        profile = GeminiAudioProfile(
            "id", "Google", "google_native", upstream.base_url,
            "gemini-3.8-flash-high", "key-value",
            temperature=0.9,
            transcribe_prompt="自定义转写指令 {source_language}",
        )
        transport = GoogleGeminiTransport(profile)
        await transport.generate(b"wave", "audio/wav", "自定义转写指令 ja")

        request = upstream.requests[0]
        assert request["body"]["generationConfig"]["temperature"] == 0.9
        # 自定义提示词由 Adapter 组装后经 transport 的 prompt 参数传入


@pytest.mark.asyncio
async def test_custom_transcribe_prompt_replaces_default(tmp_path):
    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"audio")

    def extractor(_request):
        return ExtractedAudio(clip, 10.0, 12.0, temporary=False)

    seen_prompts = []

    class Transport(GeminiAudioTransport):
        async def generate(self, audio, mime_type, prompt):
            seen_prompts.append(prompt)
            return '{"segments":[{"start":0,"end":2,"text":"内容"}]}'

    profile = GeminiAudioProfile(
        "id", "G", "google_native", "https://example.invalid",
        "gemini-3.8-flash-high", "key",
        transcribe_prompt="自定义模板：请听写{source_language}音频",
    )
    adapter = GeminiAudioAdapter(profile, Transport(), extractor=extractor, translate_fn=lambda e, s, t: e)
    await adapter.process(SegmentRequest(
        tmp_path / "audio.m4a", 10.0, 12.0, processing_mode="transcribe_then_translate"
    ))
    assert seen_prompts[0].startswith("自定义模板：请听写ja音频")


def test_parse_extracts_json_from_prose_and_clock_times():
    raw = (
        "依据听觉转写音频，输出 JSON。\n"
        '- 00:01 - 00:04: 「おい」\n'
        '输出纯JSON格式。{"segments":[{"start":"00:01","end":"00:04","text":"おい"},'
        '{"start":5,"end":6,"text":"聞こえる"}]}'
    )
    profile = GeminiAudioProfile("id", "G", "google_native", "https://x", "m", "k")
    adapter = GeminiAudioAdapter(profile, _FakeTransport(raw))
    segments, structured = adapter._parse_segments(raw, bilingual=False)
    assert structured is True
    assert segments[0]["start"] == 1.0  # "00:01" 文本时间被解析
    assert segments[1]["start"] == 5.0
