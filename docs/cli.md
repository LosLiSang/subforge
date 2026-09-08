# CLI 批处理

CLI 适合一次性批量处理：目录递归扫描、多文件并发、断点续跑。

## 常用示例

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

## 输出

每个输入文件输出两份字幕：

- `audio.ja.srt`：源语言（日文）字幕
- `audio.zh.srt`：翻译（中文）字幕

支持格式：`.mp3`、`.mp4`、`.wav`、`.m4a`、`.flac`。

## 断点续跑

断点状态默认保存在 `~/.subforge/jobs/`，行为如下：

1. 已存在有效的 `audio.zh.srt`：跳过整个文件
2. 已存在有效的 `audio.ja.srt`：跳过 ASR，只执行翻译
3. 翻译中断：重跑时只提交未完成批次
4. 状态文件损坏或与当前输入不匹配：忽略该状态并安全地重新处理
5. `--force`：忽略已有 SRT 与断点状态，从 ASR 重新开始

Library Track 的断点记录随 Item 一起保存，可随 Library 迁移。

## ASR 模型选择

| 模型 | 资源占用 | 速度 | 精度 | 建议场景 |
|------|----------|------|------|----------|
| `tiny` | 最低 | 最快 | 一般 | 测试与快速预览 |
| `base` | 低 | 很快 | 尚可 | 简单清晰的对话 |
| `small` | 较低 | 快 | 良好 | 日常音频 |
| `medium` | 中 | 中等 | 很好 | 普通日语内容 |
| `large-v3` | 高 | 慢 | 最佳 | ASMR、低语与复杂音频 |

首次使用本地 ASR 时会下载模型到 `~/.subforge/models/`，后续可复用缓存；也可以在 UI 设置页指定已有模型目录（需包含 `model.bin` 与 `config.json`），完全不访问 Hugging Face。

## 命令速查

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

!!! tip

    整轨处理选择「音频模型（Gemini 等）」目前通过 Library UI 完成；CLI 的 ASR Provider 为 `local` / `deepgram`。
