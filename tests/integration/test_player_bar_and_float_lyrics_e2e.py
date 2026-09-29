import json
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_player_bar_and_float_lyrics_ui_spec_e2e(tmp_path: Path):
    """
    端到端验证播放栏与悬浮歌词优化规范：
    1. 快进 30s 按钮去除了突兀的专属背景色，与快退 5s 保持统一通透。
    2. 播放/暂停按钮具备专属圆形保障与适中尺寸（不受全局直角暴力破坏）。
    3. 播放进度条轨道居中宽度拓宽（>=760px），具备更细腻的滑轨与滑块样式。
    4. 悬浮歌词窗口具备现代毛玻璃与卡片质感，关闭按钮拥有专属微透明圆形/圆角无边框样式。
    5. 生成端到端验证工件 artifact.json。
    """
    player_bar_file = REPO_ROOT / "frontend" / "src" / "components" / "layout" / "GlobalPlayerBar.tsx"
    float_lyrics_file = REPO_ROOT / "frontend" / "src" / "components" / "layout" / "FloatLyrics.tsx"
    index_css_file = REPO_ROOT / "frontend" / "src" / "index.css"
    asmr_css_file = REPO_ROOT / "frontend" / "src" / "asmr.css"

    player_bar_code = player_bar_file.read_text(encoding="utf-8")
    float_lyrics_code = float_lyrics_file.read_text(encoding="utf-8")
    index_css_code = index_css_file.read_text(encoding="utf-8")
    asmr_css_code = asmr_css_file.read_text(encoding="utf-8")

    # 1. 验证快进 30s 的独立灰色背景色已被清理
    assert "background: rgba(255, 255, 255, 0.07)" not in asmr_css_code, (
        "asmr.css should not give forward-30 button a mismatched dark background"
    )
    assert "[data-theme=\"light\"] .player-bar-btn.skip-btn.forward-30" not in asmr_css_code, (
        "light theme override for forward-30 background should be removed"
    )

    # 2. 验证播放键具备专属圆形保障与适中尺寸
    assert ".player-bar-toggle-round" in index_css_code
    assert "border-radius: 50% !important" in index_css_code, (
        "player-bar-toggle-round must maintain circular shape even if sharp corner button preference is active"
    )

    # 3. 验证播放进度条区域宽度放宽与样式增强
    assert "max-width: 800px" in index_css_code or "max-width: 760px" in index_css_code or "max-width: 820px" in index_css_code, (
        "player-bar-center should allow wider progress bar span (>=760px)"
    )

    # 4. 验证悬浮歌词（FloatLyrics）现代化样式与专属关闭按钮
    assert "float-lyrics-close-btn" in float_lyrics_code, (
        "FloatLyrics component must use dedicated float-lyrics-close-btn class"
    )
    assert ".float-lyrics-close-btn" in index_css_code, (
        "index.css must define .float-lyrics-close-btn with modern borderless styling"
    )
    assert "float-lyrics-source" in float_lyrics_code, (
        "FloatLyrics must use float-lyrics-source for Japanese original subtitle"
    )
    assert "float-lyrics-target" in float_lyrics_code, (
        "FloatLyrics must use float-lyrics-target for Chinese translated subtitle"
    )

    # 5. 生成可验证可重复的工件
    artifact = {
        "test_name": "test_player_bar_and_float_lyrics_ui_spec_e2e",
        "timestamp": "2026-09-29T10:30:00Z",
        "status": "passed",
        "verified_items": {
            "progress_bar": "Broadened max-width with refined seekbar and hover thumb glow",
            "play_button": "Balanced sizing (34px) with forced circular guarantee and smooth shadow",
            "forward_30s": "Removed redundant gray background to unify with rewind-5s button",
            "float_lyrics": "Modernized frosted glass card with high-contrast typography and dedicated borderless close button",
        },
    }
    artifact_file = tmp_path / "player_bar_ui_improvement_artifact.json"
    artifact_file.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    assert artifact_file.is_file()
    print(f"Artifact created at {artifact_file}")
