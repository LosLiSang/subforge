# SubForge

面向**同人音声（RJ 作品）**的本地字幕翻译工具：ASR 识别日语音频，LLM 翻译成中文，输出中日双语 SRT。

```text
Audio / Video → ASR → Timeline Fix → LLM Translate → .srt
```

SubForge 以 ASMR、低语和长音频的批量处理为核心场景。项目开源公开，但目前仍以个人使用为先。

> 当前版本同时提供 CLI 批处理和 `subforge ui` 本地 Library 工作台；niconico 直播实时翻译仍在规划中，参见 [ROADMAP.md](ROADMAP.md)。

## 适用场景

| 场景 | SubForge 的处理方式 |
|------|---------------------|
| **同人音声 / ASMR** | `--asmr` 启用低阈值 VAD、响度预处理和幻觉抑制，尽量保留耳语与短促气音 |
| **无台本的 RJ 作品** | 从音频生成日文 SRT，再翻译成中文 SRT |
| **长音频与整部作品** | 目录递归扫描、多文件并发、翻译批次并发、断点续跑 |
| **直播录像 / 视频文件** | 对下载后的受支持媒体文件执行离线转录和翻译；当前不支持直播实时字幕 |
| **本地或云端 ASR** | 默认使用 faster-whisper；对识别质量有更高要求时可选 Deepgram |

## 核心能力

- **ASMR 优化**：`--asmr` 一键配置耳语友好的 VAD、响度归一化和 Whisper 参数
- **双 ASR 后端**：本地 faster-whisper，或可选的 Deepgram 云端 ASR
- **断点续跑**：复用完整结果、已有日文 SRT 与已完成的翻译批次
- **批量处理**：目录递归扫描、多文件并发和并行 LLM 翻译
- **本地模型缓存**：Whisper 模型下载后缓存在 `~/.subforge/models/`
- **OpenAI 兼容翻译接口**：支持 DeepSeek、OpenAI、Groq、Ollama、LM Studio 等兼容端点
- **时间轴后处理**：合并过短字幕段并修正字幕间距

## 安装

前置要求：

- Python >= 3.11
- [uv](https://docs.astral.sh/uv/)
- [ffmpeg](https://ffmpeg.org/)（`--asmr` 音频预处理需要）

### 从源码运行

```bash
git clone https://github.com/LosLiSang/subforge.git
cd subforge
uv sync
uv run subforge --help
```

### 安装为全局命令

```bash
uv tool install git+https://github.com/LosLiSang/subforge.git
subforge --help
```

## 配置

首次运行会生成 `~/.subforge/config.toml`。API Key 既可以写入配置，也可以通过环境变量提供：

```bash
# LLM 翻译
export LLM_API_KEY=sk-your-key
export LLM_BASE_URL=https://api.deepseek.com/v1
export LLM_MODEL=deepseek-chat

# 可选：Deepgram 云端 ASR
export DEEPGRAM_API_KEY=dg-your-key
```

常用配置：

```toml
[asr]
provider = "local"              # local / deepgram
model = "large-v3"
device = "auto"
compute_type = "float16"

[translate]
target_lang = "zh"
batch_size = 20
workers = 8

[llm]
api_key = ""
base_url = "https://api.deepseek.com/v1"
model = "deepseek-chat"

[deepgram]
api_key = ""
model = "nova-3"
keyterms = ["気付け", "布団", "性癖"]

[processing]
concurrency = 2                 # 必须 >= 1
output_dir = ""                # 空值表示输出到源文件目录
```

> Deepgram 会把音频上传到云端，并产生 API 费用。涉及隐私或大文件批量处理前，请先确认账号额度与数据策略。

## 本地 Library UI

```bash
subforge ui
```

首次启动会打开浏览器并要求选择 Library 根目录。当前 UI 支持单音频导入、RJ 作品/直播归档、命名翻译配置、独立 Worker 任务队列、进度、取消/继续/重译/从头处理、软删除以及中日字幕同步播放器。服务只监听 `127.0.0.1`。

如果本地 Whisper 模型尚未缓存，Worker 会从 Hugging Face 下载。网络受限时可在 UI 的“设置”页填写代理，例如 `http://127.0.0.1:7890`。设置页还支持修改模型缓存/下载根目录，或为 `medium`、`large-v3` 分别选择已有的 CTranslate2 模型目录（需包含 `model.bin` 与 `config.json`）；直接目录模式完全不访问 Hugging Face。任务详情页会标出模型是“直接目录”“已缓存”还是“需下载”。

## 使用

```bash
# 普通日语音频 → 中日双语字幕
subforge audio.mp3

# ASMR / 耳语作品
subforge audio.m4a --asmr

# GPU 加速
subforge audio.m4a --asmr --device auto --compute-type float16

# 使用 Deepgram 云端 ASR
subforge audio.m4a --asr-provider deepgram

# 批量处理一个 RJ 作品目录
subforge ./RJ01499022/ --asmr --device auto --concurrency 2

# 指定输出目录；目录不存在时会自动创建
subforge audio.m4a --output-dir ./subtitles

# 忽略已有字幕与断点，从 ASR 阶段重新处理
subforge audio.m4a --force
```

每个输入文件输出两份字幕：

- `audio.ja.srt`：源语言（日文）字幕
- `audio.zh.srt`：翻译（中文）字幕

支持格式：`.mp3`、`.mp4`、`.wav`、`.m4a`、`.flac`。

## 断点续跑

SubForge 默认启用断点续跑，状态文件保存在 `~/.subforge/jobs/`：

1. 已存在有效的 `audio.zh.srt`：跳过整个文件
2. 已存在有效的 `audio.ja.srt`：跳过 ASR，只执行翻译
3. 翻译中断：重跑时只提交未完成批次
4. 状态文件损坏或与当前输入不匹配：忽略该状态并安全地重新处理
5. `--force`：忽略已有 SRT 与断点状态，从 ASR 重新开始

## ASR 模型选择

| 模型 | 资源占用 | 速度 | 精度 | 建议场景 |
|------|----------|------|------|----------|
| `tiny` | 最低 | 最快 | 一般 | 测试与快速预览 |
| `base` | 低 | 很快 | 尚可 | 简单清晰的对话 |
| `small` | 较低 | 快 | 良好 | 日常音频 |
| `medium` | 中 | 中等 | 很好 | 普通日语内容 |
| `large-v3` | 高 | 慢 | 最佳 | ASMR、低语与复杂音频 |

首次使用本地 ASR 时会下载模型到 `~/.subforge/models/`，后续可复用缓存。

## CLI 速查

```text
subforge INPUTS... [OPTIONS]

  --model TEXT
  --asr-provider local|deepgram
  --device cpu|cuda|auto
  --compute-type default|auto|float16|int8_float16|int8|float32
  --source-lang TEXT
  --target-lang TEXT
  --asmr
  --llm-api-key TEXT
  --llm-base-url TEXT
  --llm-model TEXT
  --deepgram-api-key TEXT
  --deepgram-model TEXT
  --concurrency INTEGER RANGE   必须 >= 1
  --output-dir PATH
  --force
  --config PATH
  --log-level DEBUG|INFO|WARNING|ERROR
  --version
```

## 开发

```bash
uv sync
uv run pytest tests/ -q
uv run subforge --help
```

CLI 端到端测试会使用临时配置与断点目录，不会读取个人配置、调用真实 Deepgram 或污染个人断点文件。

### 项目结构

```text
subforge/
├── cli.py                 # Click CLI 入口
├── config.py              # TOML / 环境变量 / CLI 配置合并
├── models.py              # Job / SubtitleEntry 数据模型
├── orchestrator.py        # ASR → timeline → translate 主流程
├── resume.py              # 断点状态、校验与恢复
├── events.py              # 结构化处理事件
├── library.py             # Library 文件模型、导入与可重建索引
├── worker.py              # 独立处理 Worker / JSONL 事件
├── scanner.py             # 文件和目录扫描
├── timeline.py            # 时间轴后处理
├── ui/                    # Starlette 工作台、任务队列、模板和播放器
├── asr/
│   ├── deepgram.py        # Deepgram 云端 ASR
│   ├── engine.py          # faster-whisper 本地 ASR
│   └── model_manager.py   # Whisper 模型缓存检测
└── translate/
    ├── context.py         # 批次构建与并发翻译
    ├── llm_client.py      # OpenAI 兼容 LLM 客户端
    └── srt_io.py          # SRT 文件读写
```

## 后续安排

开发顺序已经确定：

1. **批处理打磨与公开化**：保持文档、测试、打包和实现一致
2. **本地作品库 UI**：Slice 0–3 单文件闭环已完成；下一步是 RJ 整包、DLsite 刮削和封面墙
3. **实时翻译**：Windows 系统音频捕获、流式 ASR、低延迟本地翻译

详细范围、验收条件和明确不做事项见 [ROADMAP.md](ROADMAP.md)。

## 致谢

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — 基于 CTranslate2 的 Whisper 推理实现
- [OpenAI Whisper](https://github.com/openai/whisper) — SubForge 本地 ASR 使用的基础模型
- [Deepgram](https://deepgram.com/) — 可选的云端 ASR 后端

## 许可证

[MIT License](LICENSE)
