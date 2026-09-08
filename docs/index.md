# SubForge

面向**同人音声（RJ 作品）**的本地字幕翻译工具：ASR 识别日语音频，LLM 翻译成中文，输出中日双语 SRT。

```text
Audio / Video → ASR → Timeline Fix → LLM Translate → .srt
```

SubForge 以 ASMR、低语和长音频的批量处理为核心场景。项目开源公开（MIT），但以个人使用为先。

---

## 为什么是 SubForge

同人音声圈的主力作品是 **ASMR 耳语内容**，通用字幕工具做不好耳语识别。SubForge 把 ASMR 优化当作**核心差异能力**而非附属功能：低阈值 VAD、响度归一化、幻觉抑制，尽量保留耳语与短促气音。

定位决策见 [ADR-0001](adr/0001-product-positioning.md)：窄而深，日→中，不做多语言。

## 核心能力

- **ASMR 优化**：`--asmr` 一键配置耳语友好的 VAD、响度归一化和 Whisper 参数
- **多种 ASR 后端**：本地 faster-whisper、可选 Deepgram 云端，以及 [Gemini 类音频模型](model-profiles.md)（按请求时长自动分片）
- **统一模型配置**：一份 [模型 Profile](model-profiles.md) 可承担音频转写 / 文本翻译 / 文本合并，按能力过滤复用
- **断点续跑**：复用完整结果、已有源语言 SRT 与已完成的翻译批次
- **本地 Library 工作台**：导入、播放、任务中心、字幕校正与片段重处理
- **任务持久化**：任务与片段候选写入 SQLite，重启不丢，支持取消/重试/待评审
- **OpenAI 兼容翻译接口**：DeepSeek、OpenAI、Groq、Ollama、LM Studio 等兼容端点

## 快速开始

```bash
git clone https://github.com/LosLiSang/subforge.git
cd subforge
uv sync
uv run subforge --help

# 本地 Library 工作台
uv run subforge ui
```

详见[安装与配置](install.md)。

## 文档导航

| 想做什么 | 看哪页 |
|---|---|
| 装好并配置 API Key | [安装与配置](install.md) |
| 批量处理一个 RJ 作品目录 | [CLI 批处理](cli.md) |
| 导入、播放、校正字幕 | [Library 工作台](library-ui.md) |
| 接入 Gemini 当 ASR / 翻译 | [模型配置](model-profiles.md) |
| 只重做某一段的字幕 | [片段重处理](segment-reprocess.md) |
| 看任务进度、候选评审 | [任务中心](tasks.md) |
| 术语怎么定义的 | [术语表](glossary.md) |
