# 模型配置（ASR / 翻译 / 合并）

SubForge 用**一份统一的模型 Profile** 承担三类能力，靠能力标记区分，不再把 Gemini 单独归为一类：

| 能力 | 含义 |
|------|------|
| `transcribe` | 音频 → 文本，可作为 ASR 模型 |
| `translate` | 文本 → 文本，可作为翻译模型 |
| `merge` | 文本层校对，可用于分片结果的合并 |

设置页「模型配置」里勾选能力即可；ASR、翻译、合并三个下拉按能力过滤同一份 Profile 集合。

## 协议

| 协议 | 说明 |
|------|------|
| `openai_compatible` | `/chat/completions`；文本翻译用 message，音频用 `input_audio` |
| `google_native` | Google `generateContent`，inline audio |

??? example "适合当 ASR 的配置示例"

    - 名称：`raspb`（内网网关）
    - 协议：`openai_compatible`
    - 模型：`gemini-3.8-flash-high`
    - 能力：转写 + 翻译
    - 单次请求上限：按网关预算设定（默认 60 秒）

## Gemini 类模型当 ASR：分片与合并

Gemini flash 类模型**单次请求时长不宜过长**，因此以 Profile 的**单次请求上限**（`max_request_seconds`，默认 60 秒）控制：

1. 用 ffmpeg `silencedetect` 找出语音区间
2. 把语音区间**打包**成不超过上限的块，超长单段语音均匀切分
3. 逐块送模型转写，时间戳由 SubForge 确定性映射回绝对时间轴
4. 可选：交给**合并模型**做一次文本层校对

!!! warning "时间轴所有权归 SubForge"

    合并只做文本层工作：去掉分块边界重复、修标点断句、统一术语。**绝对时间轴由 SubForge 生成，合并模型不得重排时间戳**——实测 Gemini 直接产出时间轴会压缩/扭曲。

### 兜底行为

- 语音区间检测失败 → 退化为**等长分片**（仍遵守上限），绝不整段一次发送
- 合并模型失败/解析失败 → 保留原文，绝不丢条目
- ASR 结果写盘前钳制到媒体时长，丢弃完全越界的幻觉条目

## 旧配置自动迁移

旧的 `llm-profiles.json`（翻译）与 `gemini-audio-profiles.json`（Gemini 音频）在首次加载时自动合并为 `model-profiles.json`：

- 旧翻译配置 → 仅 `translate`
- 旧 Gemini 音频 → `transcribe` + `translate`，并继承单次上限与提示词模板

## 能力与入口对应

| 入口 | 过滤的能力 | 选择历史 scope |
|------|-----------|----------------|
| 作品处理 · ASR | `transcribe` | `full.asr_profile` |
| 作品处理 · 翻译配置 | `translate` | `full.translation_profile` |
| 作品处理 · 合并模型 | `merge` | `full.merge_profile` |
| 播放页 · 片段重处理 · 音频模型 | `transcribe` | `segment.asr_profile` |
| 播放页 · 片段重处理 · 翻译配置 | `translate` | `segment.translation_profile` |
