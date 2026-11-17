from __future__ import annotations

import logging
import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_DIR = Path.home() / ".subforge"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.toml"
DEFAULT_JOBS_DIR = DEFAULT_CONFIG_DIR / "jobs"

DEFAULT_CONFIG_TOML = """\
# ── ASR (Speech Recognition) ────────────────────────────────────────────
[asr]
# ASR provider: model / deepgram
provider = "model"
# Source audio language (ISO 639-1 code)
source_lang = "ja"

# ── Translation ─────────────────────────────────────────────────────────
[translate]
# Target language for translation (ISO 639-1 code)
target_lang = "zh"
# Number of subtitle entries per LLM call
batch_size = 20
# Surrounding entries sent to LLM for translation context
context_size = 10
# Max parallel LLM translation calls
workers = 20
# Optional extra instructions appended to the default subtitle rules.
prompt = ""

# ── LLM API ─────────────────────────────────────────────────────────────
[llm]
# OpenAI-compatible API key (or set LLM_API_KEY env var)
api_key = ""
# API base URL (OpenAI, DeepSeek, Ollama, Groq, etc.)
base_url = "https://api.openai.com/v1"
# Model name
model = "gpt-4o"

# ── Deepgram ASR ────────────────────────────────────────────────────────
[deepgram]
# Deepgram API key (or set DEEPGRAM_API_KEY env var)
api_key = ""
# Deepgram ASR model
model = "nova-3"
# Key terms to improve recognition of names / domain words
keyterms = []

# ── General ─────────────────────────────────────────────────────────────
[processing]
# Max audio files processed in parallel
concurrency = 2
# Output directory for generated SRT files (empty = same as source)
output_dir = ""

# ── Logging ─────────────────────────────────────────────────────────────
[logging]
# Log level: DEBUG / INFO / WARNING / ERROR
level = "INFO"
# Log file name (written to current working directory)
file = "subforge.log"
"""


@dataclass
class Config:
    # ASR
    asr_provider: str = "model"
    model: str = ""
    source_lang: str = "ja"
    # Translate
    target_lang: str = "zh"
    batch_size: int = 20
    context_size: int = 10
    translate_workers: int = 20
    translation_prompt: str = ""
    translation_global_workers: int = 0
    translation_limiter_dir: Path | None = None
    # LLM
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o"
    llm_reasoning_effort: str = ""
    llm_proxy_url: str = ""
    llm_verify_tls: bool = True
    llm_ca_bundle: str = ""
    # Network ASR task-level chunk size (seconds)
    asr_chunk_seconds: int = 60
    # Shared cross-process network ASR request pool
    remote_asr_global_workers: int = 0
    remote_asr_limiter_dir: Path | None = None
    # Deepgram ASR
    deepgram_api_key: str = ""
    deepgram_model: str = "nova-3"
    deepgram_keyterms: list[str] = field(default_factory=list)
    # 统一模型 Profile 快照（不含密钥；密钥经环境变量传入）
    asr_profile: dict | None = None
    merge_profile: dict | None = None
    # Processing
    concurrency: int = 2
    output_dir: Path | None = None
    force: bool = False
    # Logging
    log_level: str = "INFO"
    log_file: str = "subforge.log"
    # Paths
    config_path: Path = field(default=DEFAULT_CONFIG_PATH)
    jobs_dir: Path = field(default=DEFAULT_JOBS_DIR)


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
        "DEEPGRAM_API_KEY": ("deepgram", "api_key"),
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
    kwargs["asr_provider"] = toml_data.get("asr", {}).get("provider", "model")
    kwargs["model"] = toml_data.get("asr", {}).get("model", "")
    kwargs["source_lang"] = toml_data.get("asr", {}).get("source_lang", "ja")
    kwargs["target_lang"] = toml_data.get("translate", {}).get("target_lang", "zh")
    kwargs["batch_size"] = int(toml_data.get("translate", {}).get("batch_size", 20))
    kwargs["context_size"] = int(toml_data.get("translate", {}).get("context_size", 10))
    kwargs["translate_workers"] = int(toml_data.get("translate", {}).get("workers", 20))
    kwargs["translation_prompt"] = str(toml_data.get("translate", {}).get("prompt", ""))
    kwargs["translation_global_workers"] = 0
    kwargs["translation_limiter_dir"] = None
    kwargs["llm_api_key"] = toml_data.get("llm", {}).get("api_key", "")
    kwargs["llm_base_url"] = toml_data.get("llm", {}).get("base_url", "https://api.openai.com/v1")
    kwargs["llm_model"] = toml_data.get("llm", {}).get("model", "gpt-4o")
    kwargs["llm_reasoning_effort"] = toml_data.get("llm", {}).get("reasoning_effort", "")
    kwargs["llm_proxy_url"] = ""
    kwargs["llm_verify_tls"] = True
    kwargs["llm_ca_bundle"] = ""
    kwargs["asr_chunk_seconds"] = 60
    kwargs["remote_asr_global_workers"] = 0
    kwargs["remote_asr_limiter_dir"] = None
    kwargs["deepgram_api_key"] = toml_data.get("deepgram", {}).get("api_key", "")
    kwargs["deepgram_model"] = toml_data.get("deepgram", {}).get("model", "nova-3")
    keyterms = toml_data.get("deepgram", {}).get("keyterms", [])
    kwargs["deepgram_keyterms"] = [str(v) for v in keyterms] if isinstance(keyterms, list) else []
    kwargs["asr_profile"] = None
    kwargs["merge_profile"] = None
    kwargs["concurrency"] = int(toml_data.get("processing", {}).get("concurrency", 2))
    kwargs["log_level"] = toml_data.get("logging", {}).get("level", "INFO")
    kwargs["log_file"] = toml_data.get("logging", {}).get("file", "subforge.log")
    output_dir = toml_data.get("processing", {}).get("output_dir", "")
    kwargs["output_dir"] = Path(output_dir) if output_dir else None
    kwargs["force"] = False
    kwargs["config_path"] = path
    kwargs["jobs_dir"] = DEFAULT_JOBS_DIR

    # 4. Apply CLI overrides (highest priority)
    if cli_overrides:
        for key, val in cli_overrides.items():
            if val is not None and key in kwargs:
                kwargs[key] = val

    if kwargs["concurrency"] < 1:
        raise ValueError("concurrency must be at least 1")

    return Config(**kwargs)


class _DEBUGFilter(logging.Filter):
    """Reject DEBUG messages — used on StreamHandler to keep stderr clean."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno != logging.DEBUG


class _ColorFormatter(logging.Formatter):
    """Wrap each formatted line in level-specific ANSI color codes.

    Applied only to the console StreamHandler; FileHandler keeps plain text.
    """

    _RESET = "\x1b[0m"
    _COLORS = {
        logging.DEBUG:    "\x1b[37m",     # white
        logging.INFO:     "\x1b[34m",     # blue
        logging.WARNING:  "\x1b[33m",     # yellow
        logging.ERROR:    "\x1b[31m",     # red
        logging.CRITICAL: "\x1b[1;31m",   # bold red
    }

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        color = self._COLORS.get(record.levelno)
        return f"{color}{text}{self._RESET}" if color else text


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
    color_fmt = _ColorFormatter(
        "%(asctime)s  %(levelname)-7s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Clear any pre-existing handlers (e.g. from pytest or other configs)
    root.handlers.clear()

    # Stream handler — stderr, rejects DEBUG, ANSI-colored per level
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setLevel(root.level)
    stream_handler.addFilter(_DEBUGFilter())
    stream_handler.setFormatter(color_fmt)
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
