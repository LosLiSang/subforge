"""Unit tests for focused SubForge offline batch processing CLI."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from subforge.cli import main
from subforge.models import SubtitleEntry
from subforge.translate.srt_io import read_srt, write_srt
from subforge.ui.model_profiles import ModelProfileStore
from subforge.ui.settings import UiSettingsStore


@pytest.fixture
def runner():
    return CliRunner()


def test_cli_version(runner):
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "subforge, version" in result.output


def test_cli_ui_custom_options(runner):
    with patch("subforge.ui.server.run_ui") as mock_run:
        result = runner.invoke(main, ["ui", "--port", "9999", "--no-browser"])
        assert result.exit_code == 0
        mock_run.assert_called_once_with(port=9999, open_browser=False)


def test_cli_models_commands(runner, tmp_path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("[asr]\nmodel = 'tiny'\n", encoding="utf-8")

    res_list = runner.invoke(main, ["models", "list", "--config", str(cfg_path)])
    assert res_list.exit_code == 0
    assert "tiny" in res_list.output
    assert "large-v3" in res_list.output

    res_path = runner.invoke(main, ["models", "path", "--config", str(cfg_path)])
    assert res_path.exit_code == 0
    assert ".subforge" in res_path.output

    res_check = runner.invoke(main, ["models", "check", "tiny", "--config", str(cfg_path)])
    assert res_check.exit_code == 0


def test_cli_profiles_list_and_test(runner, tmp_path, monkeypatch):
    monkeypatch.setattr("subforge.cli.DEFAULT_CONFIG_DIR", tmp_path)

    # Create profile
    p_store = ModelProfileStore(tmp_path / "model-profiles.json")
    profile = p_store.save(
        name="DeepSeek",
        base_url="https://api.example.com/v1",
        model="deepseek-chat",
        api_key="sk-testkey12345",
        capabilities=["translate"],
    )

    # List profiles
    res_list = runner.invoke(main, ["profiles", "list"])
    assert res_list.exit_code == 0
    assert "DeepSeek" in res_list.output
    assert "deepseek-chat" in res_list.output

    # Test profile connection (mocked)
    with patch("subforge.cli.test_profile_connection", new_callable=AsyncMock) as mock_test:
        mock_test.return_value = (True, "连接成功")
        res_test = runner.invoke(main, ["profiles", "test", "DeepSeek"])
        assert res_test.exit_code == 0
        assert "连接成功" in res_test.output


def test_cli_jobs_commands(runner, tmp_path):
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir(parents=True)
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(f"[logging]\n[asr]\n", encoding="utf-8")

    # Create dummy job checkpoint
    dummy_job = {
        "job_key": "abc123def456",
        "media": {"path": "audio1.mp3"},
        "asr": {"status": "done"},
        "translation": {"status": "partial", "completed_batches": {"1": []}, "total_batches": 5},
        "updated_at": "2026-09-13T12:00:00Z",
    }
    (jobs_dir / "abc123def456.json").write_text(json.dumps(dummy_job), encoding="utf-8")

    with patch("subforge.config.DEFAULT_JOBS_DIR", jobs_dir):
        # List jobs
        res_list = runner.invoke(main, ["jobs", "list", "--config", str(cfg_path)])
        assert res_list.exit_code == 0
        assert "audio1.mp3" in res_list.output
        assert "1/5 batches" in res_list.output

        # Show job
        res_show = runner.invoke(main, ["jobs", "show", "abc123def", "--config", str(cfg_path)])
        assert res_show.exit_code == 0
        assert "audio1.mp3" in res_show.output

        # Clear job
        res_clear = runner.invoke(main, ["jobs", "clear", "--all", "-y", "--config", str(cfg_path)])
        assert res_clear.exit_code == 0
        assert not (jobs_dir / "abc123def456.json").exists()


def test_cli_check_command(runner, tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("[asr]\nmodel = 'tiny'\n", encoding="utf-8")
    result = runner.invoke(main, ["check", "--no-test-api", "--config", str(cfg)])
    assert result.exit_code == 0
    assert "SubForge Environment & System Doctor" in result.output
    assert "Python" in result.output


def test_cli_process_dry_run_modes(runner, tmp_path):
    audio = tmp_path / "track1.mp3"
    audio.write_bytes(b"dummy audio")
    cfg = tmp_path / "config.toml"
    cfg.write_text("[asr]\nmodel = 'tiny'\n", encoding="utf-8")

    # 1. Fresh file dry-run
    r1 = runner.invoke(main, [str(audio), "--dry-run", "--config", str(cfg)])
    assert r1.exit_code == 0
    assert "FULL PIPELINE" in r1.output

    # 2. Existing ja.srt -> TRANSLATE ONLY
    ja_srt = tmp_path / "track1.ja.srt"
    write_srt([SubtitleEntry(1, 0.0, 1.0, "テスト")], ja_srt)
    r2 = runner.invoke(main, [str(audio), "--dry-run", "--config", str(cfg)])
    assert r2.exit_code == 0
    assert "TRANSLATE ONLY" in r2.output

    # 3. Existing zh.srt -> SKIP
    zh_srt = tmp_path / "track1.zh.srt"
    write_srt([SubtitleEntry(1, 0.0, 1.0, "测试")], zh_srt)
    r3 = runner.invoke(main, [str(audio), "--dry-run", "--config", str(cfg)])
    assert r3.exit_code == 0
    assert "SKIP" in r3.output

    # 4. Mode retranslate with existing zh.srt -> RETRANSLATE ONLY (reuses ja.srt)
    r4 = runner.invoke(main, [str(audio), "--dry-run", "--mode", "retranslate", "--config", str(cfg)])
    assert r4.exit_code == 0
    assert "RETRANSLATE ONLY" in r4.output

    # 5. Mode force -> FULL PIPELINE
    r5 = runner.invoke(main, [str(audio), "--dry-run", "--force", "--config", str(cfg)])
    assert r5.exit_code == 0
    assert "FULL PIPELINE" in r5.output


def test_cli_process_profile_and_settings_inheritance(runner, tmp_path, monkeypatch):
    monkeypatch.setattr("subforge.cli.DEFAULT_CONFIG_DIR", tmp_path)

    # 1. Write ui.json with proxy and workers
    ui_settings = UiSettingsStore(tmp_path / "ui.json")
    ui_settings.set_proxy_url("http://127.0.0.1:7890")
    ui_settings.set_translate_workers(16)

    # 2. Write model-profiles.json with DeepSeek profile
    p_store = ModelProfileStore(tmp_path / "model-profiles.json")
    p_store.save(
        name="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
        api_key="sk-secret123",
        capabilities=["translate"],
        translate_prompt="自定义翻译规则",
    )

    audio = tmp_path / "test.mp3"
    audio.write_bytes(b"dummy audio")
    cfg = tmp_path / "config.toml"
    cfg.write_text("[asr]\nmodel = 'tiny'\n", encoding="utf-8")

    # Invoke dry run with --profile DeepSeek
    res = runner.invoke(
        main,
        [str(audio), "--dry-run", "--profile", "DeepSeek", "--config", str(cfg)],
    )
    assert res.exit_code == 0
    assert "Dry-run Plan" in res.output


def test_cli_retranslate_unlinks_zh_and_keeps_ja(runner, tmp_path):
    audio = tmp_path / "retrans.mp3"
    audio.write_bytes(b"audio data")
    ja_srt = tmp_path / "retrans.ja.srt"
    zh_srt = tmp_path / "retrans.zh.srt"
    write_srt([SubtitleEntry(1, 0.0, 2.0, "こんにちは")], ja_srt)
    write_srt([SubtitleEntry(1, 0.0, 2.0, "旧翻译")], zh_srt)

    cfg = tmp_path / "config.toml"
    cfg.write_text("[asr]\nmodel = 'tiny'\n", encoding="utf-8")

    # Mock orchestrator process_all
    async def fake_process_all(jobs, config, event_sink=None):
        return {"succeeded": 1, "failed": 0, "skipped": 0}

    with patch("subforge.cli.process_all", side_effect=fake_process_all):
        res = runner.invoke(
            main,
            [str(audio), "--mode", "retranslate", "--config", str(cfg)],
        )
        assert res.exit_code == 0

    # ja.srt must be preserved!
    assert ja_srt.is_file()
    # zh.srt was unlinked for retranslation
    assert not zh_srt.exists()
