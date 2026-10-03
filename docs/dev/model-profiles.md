# 模型 Profile 内部机制

用户视角的说明见[模型配置](../model-profiles.md)。

## 能力标记

一份 Profile 存在 `~/.subforge/model-profiles.json`，用能力标记区分用途，不再按“翻译配置 / Gemini 音频配置”分类：

| 能力 | 含义 | UI 文案 |
|------|------|---------|
| `transcribe` | 音频 → 文本，可作 ASR | 语音转写 |
| `translate` | 文本 → 文本 | 台本翻译 |
| `merge` | 分片结果的文本层校对 | 台本对齐合并 |

ASR、翻译、合并三个下拉按能力过滤同一份 Profile 集合。

## 协议

| 协议 | 说明 |
|------|------|
| `openai_compatible` | `/chat/completions`；文本翻译用 message，音频用 `input_audio` |
| `google_native` | Google `generateContent`，inline audio |

## 音频模型作 ASR：分片与合并

以 Profile 的 `max_request_seconds`（默认 60）控制单次请求时长：

1. ffmpeg `silencedetect` 找出语音区间；
2. 把语音区间打包成不超过上限的块，超长单段均匀切分；
3. 逐块转写，时间戳由 SubForge 确定性映射回绝对时间轴；
4. 可选：交给 `merge` 模型做文本层校对（去分块边界重复、修标点断句、统一术语）。

!!! warning "合并模型不得改时间轴"

    实测 Gemini 直接产出时间轴会压缩、扭曲。合并只做文本层工作，绝对时间轴由 SubForge 生成。

兜底行为：

- 语音区间检测失败 → 退化为等长分片（仍遵守上限），绝不整段一次发送；
- 合并失败 / 解析失败 → 保留原文，绝不丢条目；
- 写盘前钳制到媒体时长，丢弃完全越界的幻觉条目。

## 旧配置自动迁移

旧的 `llm-profiles.json` 与 `gemini-audio-profiles.json` 首次加载时合并为 `model-profiles.json`，原文件保留：

- 旧翻译配置 → 仅 `translate`；
- 旧 Gemini 音频 → `transcribe` + `translate`，继承单次上限与提示词模板。

## 能力与入口、选择历史

每次任务成功入队后，所选下拉项写入 SQLite `selection_history` 表；下拉按「最近使用 → 使用次数」排序，未出现的项保持原有确定性顺序，失效 ID 忽略。

| 入口 | 过滤能力 | selection scope |
|------|---------|-----------------|
| 作品处理 · ASR | `transcribe` | `full.asr_profile` |
| 作品处理 · 翻译 | `translate` | `full.translation_profile` |
| 作品处理 · 合并 | `merge` | `full.merge_profile` |
| 片段重处理 · 音频模型 | `transcribe` | `segment.asr_profile` |
| 片段重处理 · 翻译 | `translate` | `segment.translation_profile` |

## API Key 处理

- 保存时 Key 留空 = 保留已有值，不覆盖；
- 列表接口只返回掩码（`api_key_masked`）；
- 传给 Worker 子进程只走环境变量，不写入任务请求文件。
