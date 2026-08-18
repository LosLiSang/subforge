import os
from pathlib import Path

import pytest

from subforge.config import Config, load_config, _ensure_default_config


class TestEnsureDefaultConfig:
    def test_creates_config_dir_and_file(self, tmp_path):
        config_path = tmp_path / "config.toml"
        _ensure_default_config(config_path)
        assert config_path.exists()
        content = config_path.read_text(encoding="utf-8")
        assert "[asr]" in content
        assert 'provider = "local"' in content
        assert 'model = "medium"' in content
        assert "[translate]" in content
        assert "[llm]" in content
        assert "[deepgram]" in content
        assert "[processing]" in content

    def test_does_not_overwrite_existing(self, tmp_path):
        config_path = tmp_path / "config.toml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("[asr]\nmodel = \"large\"\n")
        _ensure_default_config(config_path)
        content = config_path.read_text()
        assert 'model = "large"' in content
        assert "[translate]" not in content  # not overwritten


class TestLoadConfigDefaults:
    def test_all_defaults(self, tmp_path):
        # Use a non-existent config file to get pure defaults
        config = load_config(config_path=tmp_path / "nonexistent.toml")
        assert config.model == "medium"
        assert config.asr_provider == "local"
        assert config.source_lang == "ja"
        assert config.target_lang == "zh"
        assert config.batch_size == 20
        assert config.context_size == 10
        assert config.llm_base_url == "https://api.openai.com/v1"
        assert config.llm_model == "gpt-4o"
        assert config.deepgram_api_key == ""
        assert config.deepgram_model == "nova-3"
        assert config.deepgram_keyterms == []
        assert config.concurrency == 2
        assert config.translate_workers == 8
        assert config.log_level == "INFO"
        assert config.log_file == "subforge.log"
        assert config.output_dir is None
        assert config.force is False
        assert config.models_dir == Path.home() / ".subforge" / "models"
        assert config.jobs_dir == Path.home() / ".subforge" / "jobs"


class TestLoadConfigFromToml:
    def test_rejects_non_positive_concurrency(self, tmp_path):
        config_path = tmp_path / "config.toml"
        config_path.write_text("[processing]\nconcurrency = 0\n", encoding="utf-8")

        with pytest.raises(ValueError, match="concurrency must be at least 1"):
            load_config(config_path)

    def test_custom_values(self, tmp_path):
        config_path = tmp_path / "config.toml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("""\
[asr]
provider = "deepgram"
model = "large"
source_lang = "en"

[translate]
target_lang = "ja"
batch_size = 30
context_size = 15

[llm]
api_key = "sk-test123"
base_url = "https://custom.api.com/v1"
model = "gpt-4o-mini"

[deepgram]
api_key = "dg-test123"
model = "nova-2"
keyterms = ["気付け", "布団"]

[processing]
concurrency = 4
output_dir = "D:/subtitles"
""", encoding="utf-8")
        config = load_config(config_path)
        assert config.model == "large"
        assert config.asr_provider == "deepgram"
        assert config.source_lang == "en"
        assert config.target_lang == "ja"
        assert config.batch_size == 30
        assert config.context_size == 15
        assert config.llm_api_key == "sk-test123"
        assert config.llm_base_url == "https://custom.api.com/v1"
        assert config.llm_model == "gpt-4o-mini"
        assert config.deepgram_api_key == "dg-test123"
        assert config.deepgram_model == "nova-2"
        assert config.deepgram_keyterms == ["気付け", "布団"]
        assert config.concurrency == 4
        assert config.output_dir == Path("D:/subtitles")


class TestEnvVarOverrides:
    def test_env_overrides_toml(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "sk-env-key")
        monkeypatch.setenv("LLM_MODEL", "gpt-4o-env")
        monkeypatch.setenv("DEEPGRAM_API_KEY", "dg-env-key")

        config_path = tmp_path / "config.toml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("""\
[llm]
api_key = "sk-toml"
base_url = "https://toml.api.com/v1"
model = "gpt-4o"

[deepgram]
api_key = "dg-toml"
""")
        config = load_config(config_path)
        assert config.llm_api_key == "sk-env-key"  # env wins over toml
        assert config.llm_model == "gpt-4o-env"
        assert config.llm_base_url == "https://toml.api.com/v1"  # no env, keeps toml
        assert config.deepgram_api_key == "dg-env-key"


class TestCliOverrides:
    def test_cli_overrides_everything(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LLM_MODEL", "gpt-4o-env")

        config_path = tmp_path / "config.toml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("[llm]\nmodel = \"gpt-4o-toml\"\n[asr]\nmodel = \"tiny\"\n")

        config = load_config(config_path, cli_overrides={
            "asr_provider": "deepgram",
            "model": "large",
            "llm_model": "gpt-4o-cli",
            "deepgram_api_key": "dg-cli",
            "deepgram_model": "nova-3",
            "deepgram_keyterms": ["社長"],
            "concurrency": 8,
            "force": True,
        })
        assert config.asr_provider == "deepgram"
        assert config.model == "large"  # CLI wins
        assert config.llm_model == "gpt-4o-cli"  # CLI > env > toml
        assert config.deepgram_api_key == "dg-cli"
        assert config.deepgram_model == "nova-3"
        assert config.deepgram_keyterms == ["社長"]
        assert config.concurrency == 8
        assert config.force is True

    def test_cli_none_does_not_override(self, tmp_path):
        config_path = tmp_path / "config.toml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("[asr]\nmodel = \"small\"\n")
        config = load_config(config_path, cli_overrides={"model": None})
        assert config.model == "small"


class TestConfigDataclass:
    def test_direct_construction(self):
        config = Config(
            model="tiny",
            source_lang="en",
            target_lang="ja",
            llm_api_key="sk-direct",
            concurrency=1,
        )
        assert config.model == "tiny"
        assert config.source_lang == "en"
        assert config.target_lang == "ja"
        assert config.llm_api_key == "sk-direct"
        assert config.concurrency == 1
        # Defaults for unspecified
        assert config.asr_provider == "local"
        assert config.batch_size == 20
        assert config.context_size == 10
        assert config.deepgram_model == "nova-3"
        assert config.deepgram_keyterms == []
        assert config.force is False
