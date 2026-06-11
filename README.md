# SubForge

同人音声 / 播客 / 视频一键字幕生成：**ASR 语音识别** + **LLM 翻译** → 双语 SRT。

```
Audio → faster-whisper ASR → timeline fix → LLM translate → .srt
```

## 场景

| 场景 | 痛点 | SubForge 怎么解决 |
|------|------|------------------|
| **同人音声 / ASMR** | 耳语、气音被 VAD 当成静音删光 | `--asmr` 一键预设：低阈值 VAD + 响度归一化 + 幻觉抑制 |
| **日语生肉** | 听不懂，网上找不到字幕 | medium 模型出日字，LLM 翻中文，双语 SRT 一起出 |
| **批量处理** | 一个作品十几条音轨，手动一条条弄 | 目录扫描 + 多文件并发，扔进去就不用管 |
| **GPU 加速** | CPU 跑 large-v3 半小时 | `--device auto` 切 GPU，3-5 分钟搞定 |
| **本地 / 离线** | API 太贵或没网 | 支持 Ollama 本地模型，模型缓存一次永久离线用 |

## 特色

- **ASMR 专优**：`--asmr` 预设解决 VAD 吞耳语、幻觉传播、吞字三大难题
- **真实并行翻译**：8 worker 并发调 LLM，6000 条字幕 ~4 分钟
- **音频预处理**：内置 ffmpeg loudnorm，-45dB 耳语自动提到正常音量再送 VAD
- **多文件并发**：目录扔进去，concurrency 个文件同时跑 ASR + 翻译
- **模型缓存**：Whisper 模型下载一次，后续完全离线
- **兼容 OpenAI API**：DeepSeek / Groq / Ollama / 任意 OpenAI 兼容端点
- **进度条**：ASR 百分比 + 翻译批次双进度条

## 快速启动

### 1. 安装

前置要求：**Python >= 3.11**、**[uv](https://docs.astral.sh/uv/)**、**[ffmpeg](https://ffmpeg.org/)**（`--asmr` 音频预处理必需）

```bash
git clone https://github.com/LosLiSang/subforge.git
cd subforge
uv sync
```

或全局安装：

```bash
uv tool install git+https://github.com/LosLiSang/subforge.git
```

### 2. 配置 API Key

```bash
export LLM_API_KEY=sk-your-key
export LLM_BASE_URL=https://api.deepseek.com/v1   # 可选，默认 OpenAI
export LLM_MODEL=deepseek-chat                     # 可选

# 可选：使用 Deepgram 云端 ASR
export DEEPGRAM_API_KEY=dg-your-key
```

### 3. 跑

```bash
# 普通音频：日语 → 中文
subforge audio.mp3

# ASMR：一键优化
subforge audio.m4a --asmr

# GPU 加速
subforge audio.m4a --asmr --device auto --compute-type float16

# Deepgram 云端 ASR（默认 nova-3）
subforge audio.m4a --asr-provider deepgram

# 批量处理整个目录
subforge ./RJ01499022/ --asmr --device auto

# 忽略已有字幕和断点，从头重新处理
subforge audio.m4a --force
```

输出：
- `audio.srt` — 源语言字幕
- `audio_zh.srt` — 翻译字幕

支持格式：`.mp3` `.mp4` `.wav` `.m4a` `.flac`

### 断点续跑

SubForge 默认启用断点续跑，状态文件统一保存在 `~/.subforge/jobs/`：

- 如果已存在完整的 `audio_zh.srt`，再次处理时会跳过整个文件。
- 如果已存在有效的 `audio.srt`，会跳过 ASR，只继续翻译。
- 翻译阶段按批次保存进度，中断或失败后重跑时只提交未完成批次给 LLM。
- 使用 `--force` 可忽略已有 SRT 和断点状态，从 ASR 阶段重新开始。

### 配置文件

首次运行自动生成 `~/.subforge/config.toml`（带完整注释）。常用选项：

```toml
[asr]
provider = "local"                 # local / deepgram
model = "large-v3"               # 推荐大模型
device = "auto"                  # 有 GPU 就 auto
compute_type = "float16"         # GPU 最快

[llm]
api_key = ""                     # 或用环境变量 LLM_API_KEY
base_url = "https://api.deepseek.com/v1"
model = "deepseek-chat"

[deepgram]
api_key = ""                     # 或用环境变量 DEEPGRAM_API_KEY
model = "nova-3"
keyterms = ["気付け", "布団", "性癖"]  # 可选，提升专有词/易错词识别

[processing]
concurrency = 2                  # 同时处理几个文件
```

> Deepgram 是云端 ASR，会上传音频到 Deepgram 并产生 API 费用。涉及隐私或大文件批量处理前，先确认账号额度和数据策略。

### ASR 模型选型

| 模型 | 显存 / 内存 | 相对速度 | 精度 | 适合场景 |
|------|------------|---------|------|---------|
| `tiny` | ~1 GB | 最快 | 一般 | 快速预览、测试 |
| `base` | ~1 GB | 很快 | 尚可 | 简单对话 |
| `small` | ~2 GB | 快 | 良好 | 日常使用 |
| `medium` | ~5 GB | 中等 | 很好 | 默认选择，日语够用 |
| `large-v3` | ~10 GB | 慢 | 最佳 | ASMR / 低语 / 复杂音频 |

> 首次使用会自动下载模型到 `~/.subforge/models/`，后续完全离线。

### CLI 速查

```
subforge INPUTS... [OPTIONS]

  --model TEXT           tiny / base / small / medium / large-v3
  --asr-provider local|deepgram  默认 local
  --device cpu|cuda|auto
  --compute-type default|auto|float16|int8_float16|int8|float32
  --source-lang TEXT     默认 ja
  --target-lang TEXT     默认 zh
  --asmr                 ASMR 预设（VAD + 响度 + 幻觉抑制）
  --llm-api-key TEXT
  --llm-base-url TEXT
  --llm-model TEXT
  --deepgram-api-key TEXT
  --deepgram-model TEXT  默认 nova-3
  --concurrency INT      默认 2
  --output-dir PATH
  --force                忽略已有 SRT 和断点，从 ASR 重新开始
  --config PATH          配置文件路径（默认 ~/.subforge/config.toml）
  --log-level DEBUG|INFO|WARNING|ERROR  默认 INFO
```

## 开发调试

```bash
# 安装开发依赖
uv sync

# 跑测试（106 条）
uv run pytest tests/ -q

# 单文件测试
uv run pytest tests/test_context.py -v

# 调试日志
subforge audio.m4a --log-level DEBUG --asmr

# 日志文件
tail -f subforge.log
```

### 项目结构

```
subforge/
├── cli.py              # Click CLI 入口
├── config.py           # 配置加载（TOML → dataclass）
├── models.py           # Job / SubtitleEntry 数据模型
├── orchestrator.py     # 主流程：ASR → timeline → translate
├── scanner.py          # 文件扫描（支持目录递归）
├── timeline.py         # 时间轴后处理（合并短段 / 间距调整）
├── asr/
│   ├── engine.py       # faster-whisper 转录封装
│   └── model_manager.py # 模型缓存检测
└── translate/
    ├── context.py      # 批次构建 + 并发翻译调度
    ├── llm_client.py   # LLM API 客户端（httpx + 重试）
    └── srt_io.py       # SRT 文件读写
tests/
├── conftest.py          # pytest fixtures
├── test_config.py
├── test_context.py
├── test_asr_engine.py
├── test_orchestrator.py
├── test_scanner.py
├── test_e2e.py
├── test_llm_client.py
├── test_models.py
├── test_srt_io.py
├── test_timeline.py
└── test_v02_optimize.py # v0.2 优化相关测试
```

### 参数流

```
config.toml [asr].device → Config field → orchestrator kwarg → engine parameter → WhisperModel(...)
         CLI override ──────────────────────────────────────────────────────────┘
         环境变量 ─────────────────────────────────────────────┘
```

## 致谢

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — 基于 CTranslate2 的高效 Whisper 推理，SubForge 的 ASR 核心
- [OpenAI Whisper](https://github.com/openai/whisper) — 语音识别基础模型

## 许可证

MIT License

## 后续开发

- [ ] **断点续跑**：长音频中断后从上次进度继续
- [ ] **多目标语言**：一次翻译出 en + zh + ko 多份 SRT
