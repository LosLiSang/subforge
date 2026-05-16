from __future__ import annotations

import logging
import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_DIR = Path.home() / ".subforge"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.toml"
DEFAULT_MODELS_DIR = DEFAULT_CONFIG_DIR / "models"

DEFAULT_CONFIG_TOML = """\
[asr]
model = "medium"
source_lang = "ja"

[translate]
target_lang = "zh"
batch_size = 20
context_size = 10
workers = 8

[llm]
api_key = ""
base_url = "https://api.openai.com/v1"
model = "gpt-4o"

[processing]
concurrency = 2
output_dir = ""

[logging]
level = "INFO"
file = "subforge.log"
"""


@dataclass
class Config:
    # ASR
    model: str = "medium"
    source_lang: str = "ja"
    # Translate
    target_lang: str = "zh"
    batch_size: int = 20
    context_size: int = 10
    translate_workers: int = 8
    # LLM
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o"
    # Processing
    concurrency: int = 2
    output_dir: Path | None = None
    # Logging
    log_level: str = "INFO"
    log_file: str = "subforge.log"
    # Paths
    config_path: Path = field(default=DEFAULT_CONFIG_PATH)
    models_dir: Path = field(default=DEFAULT_MODELS_DIR)


def _ensure_default_config(config_path: Path) -> None:
    """Create default config.toml if it doesn't exist."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if not config_path.exists():
        config_path.write_text(DEFAULT_CONFIG_TOML, encoding="utf-8")


def _load_toml(config_path: Path) -> dict:
    """Load and parse the TOML config file. Returns {} if file missing."""
    _ensure_default_config(config_path)
    try:
        with open(config_path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def _apply_env_overrides(cfg: dict) -> None:
    """Apply environment variable overrides in-place."""
    env_map = {
        "LLM_API_KEY": ("llm", "api_key"),
        "LLM_BASE_URL": ("llm", "base_url"),
        "LLM_MODEL": ("llm", "model"),
        "SUBFORGE_LOG_LEVEL": ("logging", "level"),
    }
    for env_var, (section, key) in env_map.items():
        val = os.environ.get(env_var)
        if val:
            cfg.setdefault(section, {})[key] = val


def load_config(
    config_path: Path | None = None,
    cli_overrides: dict | None = None,
) -> Config:
    """Load configuration with priority: CLI > env > config.toml > defaults.

    Args:
        config_path: Override path to config.toml.
        cli_overrides: Dict of CLI-supplied values keyed by Config field name.
    """
    path = config_path or DEFAULT_CONFIG_PATH

    # 1. Load TOML defaults
    toml_data = _load_toml(path)

    # 2. Apply env var overrides
    _apply_env_overrides(toml_data)

    # 3. Build merged kwargs dict
    kwargs: dict = {}
    kwargs["model"] = toml_data.get("asr", {}).get("model", "medium")
    kwargs["source_lang"] = toml_data.get("asr", {}).get("source_lang", "ja")
    kwargs["target_lang"] = toml_data.get("translate", {}).get("target_lang", "zh")
    kwargs["batch_size"] = int(toml_data.get("translate", {}).get("batch_size", 20))
    kwargs["context_size"] = int(toml_data.get("translate", {}).get("context_size", 10))
    kwargs["translate_workers"] = int(toml_data.get("translate", {}).get("workers", 8))
    kwargs["llm_api_key"] = toml_data.get("llm", {}).get("api_key", "")
    kwargs["llm_base_url"] = toml_data.get("llm", {}).get("base_url", "https://api.openai.com/v1")
    kwargs["llm_model"] = toml_data.get("llm", {}).get("model", "gpt-4o")
    kwargs["concurrency"] = int(toml_data.get("processing", {}).get("concurrency", 2))
    kwargs["log_level"] = toml_data.get("logging", {}).get("level", "INFO")
    kwargs["log_file"] = toml_data.get("logging", {}).get("file", "subforge.log")
    output_dir = toml_data.get("processing", {}).get("output_dir", "")
    kwargs["output_dir"] = Path(output_dir) if output_dir else None
    kwargs["config_path"] = path
    kwargs["models_dir"] = DEFAULT_MODELS_DIR

    # 4. Apply CLI overrides (highest priority)
    if cli_overrides:
        for key, val in cli_overrides.items():
            if val is not None and key in kwargs:
                kwargs[key] = val

    return Config(**kwargs)


class _DEBUGFilter(logging.Filter):
    """Reject DEBUG messages — used on StreamHandler to keep stderr clean."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno != logging.DEBUG


def setup_logging(config: Config) -> None:
    """Initialize the logging system.

    Configures two handlers:
    - StreamHandler(sys.stderr): INFO+ (DEBUG filtered out)
    - FileHandler(config.log_file): all levels

    If the file handler cannot be created, degrades gracefully to stderr-only.
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, config.log_level.upper(), logging.INFO))

    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-7s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Clear any pre-existing handlers (e.g. from pytest or other configs)
    root.handlers.clear()

    # Stream handler — stderr, rejects DEBUG
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setLevel(root.level)
    stream_handler.addFilter(_DEBUGFilter())
    stream_handler.setFormatter(fmt)
    root.addHandler(stream_handler)

    # File handler — all levels
    try:
        file_handler = logging.FileHandler(config.log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except OSError as e:
        root.warning("Cannot create log file %s: %s — logging to stderr only",
                      config.log_file, e)
