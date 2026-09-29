import asyncio
import json
import struct
import wave
from pathlib import Path

import pytest

from subforge.segment_processing import ExtractedAudio, SegmentRequest
from subforge.gemini_audio import (
    GeminiAudioAdapter,
    GeminiAudioError,
    GeminiAudioProfile,
    GoogleGeminiTransport,
    OpenAICompatibleAudioTransport,
)
from subforge.models import SubtitleEntry

REPO_ROOT = Path(__file__).resolve().parents[2]


def _generate_test_wav(path: Path, duration_secs: float = 2.0, sample_rate: int = 16000):
    path.parent.mkdir(parents=True, exist_ok=True)
    n_samples = int(duration_secs * sample_rate)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        for _ in range(n_samples):
            wf.writeframes(struct.pack("<h", 0))


class MockCotAudioTransport:
    """模拟大模型输出混入思考链（CoT）及末尾有效 JSON 的 Transport。"""

    def __init__(self, raw_response: str) -> None:
        self.raw_response = raw_response
        self.call_count = 0

    async def generate(self, audio: bytes, mime_type: str, prompt: str) -> str:
        self.call_count += 1
        return self.raw_response


@pytest.mark.asyncio
async def test_gemini_asr_cot_cleaning_and_player_sticky_e2e(tmp_path: Path):
    """
    端到端测试：
    1. 验证 Gemini ASR 解析能穿透思考过程（CoT），精准提取末尾 JSON，不留思考块残留。
    2. 验证纯英文思考无语音输出时，安全处理为空分段，不污染字幕。
    3. 验证前端播放页（Player）中包含 sticky 工具栏配置与样式。
    4. 生成最终可重复验证的工件 artifact。
    """
    wav_file = tmp_path / "test_clip.wav"
    _generate_test_wav(wav_file, duration_secs=5.0)

    # 模拟配图 3 中的真实混合思考文本：
    cot_mixed_output = (
        "- The user wants transcription of a Japanese audio clip.\n"
        "- Constraints: - Output ONLY valid JSON starting with `{` and ending with `}`.\n"
        "- No markdown, no commentary, no quotes.\n"
        '- JSON format: `{"segments":[{"start":0.5,"end":2.1,"text":"原文"}, ...]}`\n'
        "- `start` and `end` must be numbers (seconds).\n"
        "- Transcript verbatim ja audio (ASMR whispering / mouth sounds / etc.).\n"
        'Audio analysis: 0:00 - 0:02: "たくさん舐められた後だよ" (whispered)\n'
        '0:02.5 - 0:04: "やらしい"\n'
        "Rest is ASMR sound effects / licking / breathing.\n"
        "Output JSON format cleanly."
        '{"segments":[{"start":0.0,"end":2.3,"text":"たくさん舐められた後だよ"},{"start":2.8,"end":4.2,"text":"やらしい"}]}'
    )

    profile = GeminiAudioProfile(
        profile_id="test_profile",
        name="test_cot_cleaning",
        protocol="openai_compatible",
        base_url="http://test-server/v1",
        model="gemini-3.8-flash-high",
        api_key="test-key",
        max_segment_seconds=60,
        default_processing_mode="transcribe",
    )

    transport = MockCotAudioTransport(cot_mixed_output)

    adapter = GeminiAudioAdapter(
        profile,
        transport,
        extractor=lambda req: ExtractedAudio(path=wav_file, start=10.0, end=15.0, temporary=False),
        speech_regions=lambda p, d: [(0.0, 5.0)],
        chunk_cutter=lambda p, s, e: wav_file.read_bytes(),
    )

    request = SegmentRequest(
        media_path=wav_file,
        target_start=10.0,
        target_end=15.0,
        source_language="ja",
        target_language="zh",
        processing_mode="transcribe",
    )

    # 1. 执行转写并验证字幕条目
    candidate = await adapter.process(request)
    assert candidate.processor == "gemini"
    assert len(candidate.source_entries) == 2, f"Expected 2 entries, got {len(candidate.source_entries)}"

    # 验证两句原文字幕完全清洗了英文 CoT 分析
    assert candidate.source_entries[0].text == "たくさん舐められた後だよ"
    assert candidate.source_entries[1].text == "やらしい"
    assert "The user wants" not in candidate.source_entries[0].text
    assert "Audio analysis" not in candidate.source_entries[0].text

    # 2. 验证纯英文思考无语音输出时不会回退为污染字幕
    pure_cot_output = (
        "- The user wants transcription of a Japanese audio clip.\n"
        "Audio analysis: Only breathing and ASMR noises detected. No human speech.\n"
        "Let's double check: No spoken words found."
    )
    pure_cot_adapter = GeminiAudioAdapter(
        profile,
        MockCotAudioTransport(pure_cot_output),
        extractor=lambda req: ExtractedAudio(path=wav_file, start=10.0, end=15.0, temporary=False),
        speech_regions=lambda p, d: [(0.0, 5.0)],
        chunk_cutter=lambda p, s, e: wav_file.read_bytes(),
    )
    with pytest.raises(GeminiAudioError) as exc_info:
        await pure_cot_adapter.process(request)
    assert "未在片段中识别出任何文本" in str(exc_info.value)

    # 3. 验证前端播放页（Player）中包含 sticky 头部和样式配置
    player_index_file = REPO_ROOT / "frontend" / "src" / "pages" / "Player" / "index.tsx"
    player_content = player_index_file.read_text(encoding="utf-8")
    assert "player-sticky-header" in player_content, "Player component must use player-sticky-header container"

    index_css_file = REPO_ROOT / "frontend" / "src" / "index.css"
    css_content = index_css_file.read_text(encoding="utf-8")
    assert ".player-sticky-header" in css_content, "index.css must define .player-sticky-header"
    assert "position: sticky" in css_content, "Sticky positioning must be set for .player-sticky-header"

    # 4. 生成可验证且可重复的工件
    artifact = {
        "test_name": "test_gemini_asr_cot_cleaning_and_player_sticky_e2e",
        "timestamp": "2026-09-29T10:00:00Z",
        "status": "passed",
        "verified_features": [
             {
                 "feature": "cot_cleaning_and_robust_json_extraction",
                 "raw_input_snippet": cot_mixed_output[:120] + "...",
                 "extracted_entries": [
                     {"index": e.index, "start": e.start, "end": e.end, "text": e.text}
                     for e in candidate.source_entries
                 ],
             },
             {
                 "feature": "pure_cot_no_speech_safeguard",
                 "result": "Cleanly rejected without polluting subtitles",
             },
             {
                 "feature": "frontend_player_sticky_header",
                 "checked_files": [
                     str(player_index_file.relative_to(REPO_ROOT)),
                     str(index_css_file.relative_to(REPO_ROOT)),
                 ],
             },
        ],
    }

    artifact_file = tmp_path / "gemini_cot_and_sticky_artifact.json"
    artifact_file.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    assert artifact_file.is_file()
    print(f"Artifact successfully generated at: {artifact_file}")
    assert artifact["status"] == "passed"
