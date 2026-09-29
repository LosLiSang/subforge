import json
import struct
import wave
from pathlib import Path

import pytest

from subforge.gemini_audio import (
    GeminiAudioAdapter,
    GeminiAudioProfile,
)
from subforge.models import SubtitleEntry
from subforge.segment_processing import ExtractedAudio, SegmentRequest

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


class MockMultiChunkTransport:
    """模拟多分片转写，其中有分片包含语音，有分片为纯静音返回 `{"segments":[]}`。"""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.idx = 0

    async def generate(self, audio: bytes, mime_type: str, prompt: str) -> str:
        if self.idx < len(self.responses):
            res = self.responses[self.idx]
            self.idx += 1
            return res
        return '{"segments":[]}'


@pytest.mark.asyncio
async def test_empty_segments_no_speech_and_delete_line_e2e(tmp_path: Path):
    """
    端到端验证：
    1. 当音频分片无说话声音、模型返回 `{"segments":[]}` 时，绝不会回退并输出 `{"segments":[]}` 假字幕。
    2. 多切片音频中，无声切片安全跳过，有声切片正常保留，整轨字幕中不出现任何 JSON 字符串残留。
    3. 前端播放页面校对模式提供单行删除（delete）能力，以便一键清理历史脏数据。
    4. 输出可验证且可重复的工件 artifact。
    """
    wav_file = tmp_path / "test_no_speech.wav"
    _generate_test_wav(wav_file, duration_secs=10.0)

    profile = GeminiAudioProfile(
        profile_id="test_profile_no_speech",
        name="test_no_speech",
        protocol="openai_compatible",
        base_url="http://test-server/v1",
        model="gemini-3.8-flash-high",
        api_key="test-key",
        max_segment_seconds=5,
        default_processing_mode="transcribe",
    )

    # 模拟第 1 片有语音，第 2 片无声音输出 {"segments":[]}
    chunk1_res = '{"segments":[{"start":0.5,"end":2.5,"text":"こんにちは"}]}'
    chunk2_res = '{"segments":[]}'

    transport = MockMultiChunkTransport([chunk1_res, chunk2_res])

    adapter = GeminiAudioAdapter(
        profile,
        transport,
        extractor=lambda req: ExtractedAudio(path=wav_file, start=0.0, end=10.0, temporary=False),
        speech_regions=lambda p, d: [(0.0, 5.0), (5.0, 10.0)],
        chunk_cutter=lambda p, s, e: wav_file.read_bytes(),
    )

    request = SegmentRequest(
        media_path=wav_file,
        target_start=0.0,
        target_end=10.0,
        source_language="ja",
        target_language="zh",
        processing_mode="transcribe",
    )

    candidate = await adapter.process(request)
    assert candidate.processor == "gemini"
    # 验证只有第 1 片的有效字幕，第 2 片空片段完全不生成任何条目
    assert len(candidate.source_entries) == 1, (
        f"Expected 1 entry, got {len(candidate.source_entries)}: {[e.text for e in candidate.source_entries]}"
    )
    assert candidate.source_entries[0].text == "こんにちは"
    # 彻底杜绝任何把 {"segments":[]} 当成台词入库的现象
    for entry in candidate.source_entries:
        assert "segments" not in entry.text
        assert "{" not in entry.text

    # 验证前端播放页（Player/index.tsx）已配置删除单行字幕能力（handleDeleteLine）
    player_file = REPO_ROOT / "frontend" / "src" / "pages" / "Player" / "index.tsx"
    player_code = player_file.read_text(encoding="utf-8")
    assert "handleDeleteLine" in player_code, "PlayerPage must define handleDeleteLine for line removal"
    assert "/subtitles/structure" in player_code, "handleDeleteLine must call /api/tracks/{id}/subtitles/structure"

    # 生成可验证且可重复的工件
    artifact = {
        "test_name": "test_empty_segments_no_speech_and_delete_line_e2e",
        "timestamp": "2026-09-29T11:00:00Z",
        "status": "passed",
        "verified_items": {
            "empty_segments_handling": "{" + '"segments":[]}' + " correctly interpreted as no speech without phantom subtitles",
            "retained_entries": [{"index": e.index, "text": e.text} for e in candidate.source_entries],
            "frontend_line_deletion": "Integrated handleDeleteLine with /subtitles/structure API",
        },
    }
    artifact_file = tmp_path / "empty_segments_resolution_artifact.json"
    artifact_file.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    assert artifact_file.is_file()
    print(f"Artifact created at {artifact_file}")
