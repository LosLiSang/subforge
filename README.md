# SubForge

Automatic subtitle generation tool: **ASR (Whisper)** + **LLM translation** → bilingual SRT files.

Pipeline: `Audio → faster-whisper ASR → timeline fix → LLM translate → .srt`

## Features

- **ASR** via [faster-whisper](https://github.com/SYSTRAN/faster-whisper) with local model caching
- **Translation** via any OpenAI-compatible LLM API with configurable parallelism
- **Timeline post-processing**: merge short segments, adjust gaps for readable subtitles
- Multi-file concurrency (process several audio files in parallel)
- Progress bars for both ASR and translation stages
- Structured logging (stderr + file)

## Requirements

- Python 3.11+
- ~2 GB disk for Whisper medium model (downloaded on first run)

## Installation

```bash
# From local source (editable, with dev dependencies)
uv sync

# Install as global tool
uv tool install .

# From Git
uv tool install git+https://github.com/<user>/subforge.git

# pip
pip install .
```

## Quick Start

```bash
# Set your LLM API key (once)
export LLM_API_KEY=sk-...

# Generate subtitles: Japanese audio → Chinese SRT
subforge audio.mp3

# Batch process a directory, English target
subforge ./downloads/ --target-lang en --concurrency 4

# Large model for better accuracy, custom API endpoint
subforge video.mp4 --model large --llm-base-url https://your-api.com/v1
```

## Pipeline

```
Audio file → ASR (Whisper) → raw segments
    → merge short entries (< 300ms)
    → adjust inter-segment gaps
    → write source SRT (e.g. video.srt)
    → LLM translate in parallel batches
    → write target SRT (e.g. video_zh.srt)
```

## Configuration

SubForge reads from `~/.subforge/config.toml` (auto-created on first run). Priority: **CLI flag > env var > config.toml > default**.

```toml
[asr]
model = "medium"        # tiny / base / small / medium / large
source_lang = "ja"

[translate]
target_lang = "zh"
batch_size = 20         # entries per LLM call
context_size = 10       # surrounding entries for context
workers = 8             # parallel LLM calls

[llm]
api_key = ""            # or set LLM_API_KEY env var
base_url = "https://api.openai.com/v1"
model = "gpt-4o"

[processing]
concurrency = 2         # max parallel files
output_dir = ""         # default: same as source

[logging]
level = "INFO"
file = "subforge.log"
```

### Environment variables

| Variable | Config key |
|----------|-----------|
| `LLM_API_KEY` | `llm.api_key` |
| `LLM_BASE_URL` | `llm.base_url` |
| `LLM_MODEL` | `llm.model` |
| `SUBFORGE_LOG_LEVEL` | `logging.level` |

### CLI options

```
subforge [OPTIONS] INPUTS...

  --model TEXT          ASR model size (tiny/base/small/medium/large)
  --source-lang TEXT    Source language code (default: ja)
  --target-lang TEXT    Target language code (default: zh)
  --concurrency INT     Max parallel files (default: 2)
  --llm-api-key TEXT    OpenAI API key
  --llm-base-url TEXT   OpenAI API base URL
  --llm-model TEXT      LLM model name
  --output-dir PATH     Output directory for SRT files
  --config PATH         Path to config.toml
  --log-level [DEBUG|INFO|WARNING|ERROR]
```

## Supported formats

`.mp3` `.mp4` `.wav` `.m4a` `.flac`

## LLM providers

Any OpenAI-compatible endpoint works:

| Provider | base_url | model example |
|----------|----------|--------------|
| OpenAI | `https://api.openai.com/v1` | `gpt-4o` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| Ollama (local) | `http://localhost:11434/v1` | `qwen3:32b` |
| Groq | `https://api.groq.com/openai/v1` | `llama-3.3-70b` |

## Example

```bash
# ASMR (Japanese → Chinese) with large model + DeepSeek
export LLM_API_KEY=sk-xxx
export LLM_BASE_URL=https://api.deepseek.com/v1
export LLM_MODEL=deepseek-chat

subforge ./RJ01499022.mp3 --model large
```

This produces:
- `RJ01499022.srt` — Japanese subtitles
- `RJ01499022_zh.srt` — Chinese translation
