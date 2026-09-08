# 字幕修订与片段重处理 — Requirements

## 背景与目标

SubForge 已能为长音频生成源语言字幕和翻译字幕，但自动结果可能在局部出现漏识、专有名词错误、翻译错误或切分不合理。用户需要在不重新处理整条 Track 的前提下修正正式字幕，或选择一小段原媒体重新生成候选字幕。

本功能把“人工修改正式字幕”和“模型重新生成候选字幕”分开：

- **字幕校正**：用户直接修改正式字幕。
- **片段重处理**：用户选择连续时间范围，通过片段处理器生成候选结果；只有用户确认后才替换正式字幕。

长音频默认处理链保持为 faster-whisper/Deepgram → 源语言字幕 → 文本 LLM → 翻译字幕。Gemini 作为独立的原生音频模型类别，仅用于短片段候选生成，不替代长音频主链。

## 范围

### In scope

- 在播放器字幕列表中修改单条源语言字幕和翻译字幕
- 调整单条字幕开始/结束时间
- 合并相邻字幕、拆分字幕、删除字幕
- 保存前校验空文本、无效时间、倒序和重叠
- 修改正式字幕前建立安全快照，并支持撤销最近一次修改或恢复自动生成基线
- 选择单条或连续字幕形成片段范围
- 使用现有 Whisper 链或 Gemini 原生音频模型生成候选字幕
- 候选结果与正式字幕对比，确认后替换，放弃时不产生正式资产变化
- Gemini 同时支持 Google 原生 generateContent 和 OpenAI-compatible input_audio 协议
- Gemini 处理模式可选：转写后交给现有文本 LLM 翻译，或一次生成源文和译文
- Gemini 配置测试、代理、TLS 和密钥安全

### Out of scope

- 波形时间轴和逐帧视频编辑
- ASS 字幕样式、字体、位置和特效
- 多人协作、评论和审核流
- Gemini 处理整条长音频
- 信任 Gemini 自生成的细粒度时间戳
- 只保留目标译文而丢弃源语言文本
- 无限字幕历史、分支或 Git 式版本管理

## 需求（EARS）

### R1. 单条字幕校正

- **R1.1** WHEN 用户编辑一条源语言字幕或翻译字幕并保存 THE SYSTEM SHALL 原子写回对应正式 SRT。
- **R1.2** WHEN 用户修改字幕时间 THE SYSTEM SHALL 拒绝负数、开始时间不早于结束时间、超出媒体时长或造成非法倒序的结果。
- **R1.3** WHEN 修改导致字幕与相邻条目重叠 THE SYSTEM SHALL 明确提示冲突并要求用户修正，不得静默保存。
- **R1.4** WHEN 保存成功 THE SYSTEM SHALL 重新编号字幕，并使播放器和字幕导出立即读取新结果。
- **R1.5** IF 任意一个正式字幕文件写入失败 THEN THE SYSTEM SHALL 保留修改前的全部正式字幕，不产生源文已更新而译文未更新的半完成状态。

### R2. 字幕结构操作

- **R2.1** WHEN 用户合并连续字幕 THE SYSTEM SHALL 使用第一条开始时间、最后一条结束时间，并允许用户确认合并后的源文和译文。
- **R2.2** WHEN 用户拆分字幕 THE SYSTEM SHALL 要求拆分点位于原时间范围内，并生成互不倒序的两个条目。
- **R2.3** WHEN 用户删除字幕 THE SYSTEM SHALL 显示待删除的源文、译文和时间范围并要求确认。
- **R2.4** WHEN 源字幕和翻译字幕条数不一致 THE SYSTEM SHALL 仍允许内容校正，但结构操作必须先明确对应关系，不得按数组位置静默误配。

### R3. 安全快照与恢复

- **R3.1** BEFORE 第一次人工校正或第一次片段替换 THE SYSTEM SHALL 保存不可变的自动生成基线。
- **R3.2** BEFORE 每次正式字幕写入 THE SYSTEM SHALL 保存最近一次修改前快照。
- **R3.3** WHEN 用户选择撤销最近一次修改 THE SYSTEM SHALL 原子恢复源字幕和翻译字幕快照。
- **R3.4** WHEN 用户选择恢复自动生成版本 THE SYSTEM SHALL 显示影响范围并要求确认。
- **R3.5** THE SYSTEM SHALL 不在 SQLite 中保存字幕正文；字幕文件和修订快照属于可随 Library 迁移的文件系统资产。

### R4. 片段选择

- **R4.1** WHEN 用户选择单条或连续字幕 THE SYSTEM SHALL 以第一条开始时间和最后一条结束时间形成目标替换范围。
- **R4.2** IF 用户选择不连续字幕 THEN THE SYSTEM SHALL 拒绝创建一次片段重处理请求。
- **R4.3** WHEN 截取媒体 THE SYSTEM SHALL 在目标范围前后增加可配置上下文，默认各 2 秒，并裁切到媒体有效范围。
- **R4.4** THE SYSTEM SHALL 将目标替换范围与实际送入模型的上下文范围分别记录，模型上下文不得扩大正式替换范围。
- **R4.5** IF 目标范围超过所选片段处理器的限制 THEN THE SYSTEM SHALL 在调用模型前拒绝请求并显示允许的最大时长。

### R5. 候选生成与确认

- **R5.1** WHEN 片段处理完成 THE SYSTEM SHALL 返回候选源字幕、候选翻译字幕、处理器信息和警告，不得直接写正式 SRT。
- **R5.2** WHEN 用户查看候选 THE SYSTEM SHALL 同时展示原结果与候选结果，并提供接受、放弃和进入手动校正三个动作。
- **R5.3** WHEN 用户确认接受候选 THE SYSTEM SHALL 先建立快照，再原子替换目标范围内的正式字幕。
- **R5.4** WHEN 用户放弃候选或处理失败 THE SYSTEM SHALL 不修改正式字幕、断点状态或 Track 的已完成状态。
- **R5.5** IF 模型返回空文本、缺少必需语言、无法解析的结构或语义空结果 THEN THE SYSTEM SHALL 将本次候选生成判为失败，不得把空结果作为候选或缓存。

### R6. 时间轴所有权

- **R6.1** THE SYSTEM SHALL 把 SubForge 的正式字幕时间轴视为真相来源，不信任 Gemini 输出的时间戳。
- **R6.2** WHEN Gemini 返回一个源文块 THE SYSTEM SHALL 默认复用用户所选目标范围作为候选时间范围。
- **R6.3** IF Gemini 返回多条文本且无法与现有字幕建立确定对应关系 THEN THE SYSTEM SHALL 合并为一个候选段或要求用户手动拆分，不得自动伪造细粒度时间轴。
- **R6.4** WHEN Whisper 片段处理器返回相对时间戳 THE SYSTEM SHALL 加上实际音频截取起点偏移，并只允许替换目标范围内的结果。

### R7. 片段处理器

- **R7.1** THE SYSTEM SHALL 通过统一片段处理 seam 调用不同实现，UI 和字幕存储不得了解 Whisper 或 Gemini 的传输细节。
- **R7.2** THE SYSTEM SHALL 至少提供 Whisper 片段 Adapter 和 Gemini 原生音频 Adapter。
- **R7.3** WHEN 使用 Whisper 片段 Adapter THE SYSTEM SHALL 允许选择现有 ASR 后端、模型和 ASMR 预设，并使用现有文本 LLM Profile 生成翻译字幕。
- **R7.4** WHEN 使用与当前相同的模型和参数重试 THE SYSTEM SHALL 提示结果可能与现有字幕相同。
- **R7.5** WHEN 片段任务被取消 THE SYSTEM SHALL 停止后续翻译和候选生成，不修改正式字幕。

### R8. Gemini 原生音频模型

- **R8.1** THE SYSTEM SHALL 将 Gemini 配置为独立的原生音频模型 Profile，不放入 Whisper 模型下拉或普通文本 LLM Profile。
- **R8.2** THE SYSTEM SHALL 支持 `google_native` 协议，通过 Gemini generateContent 发送 inline audio。
- **R8.3** THE SYSTEM SHALL 支持 `openai_compatible` 协议，通过兼容端点的 input_audio 内容发送音频。
- **R8.4** WHEN 处理模式为 `transcribe_then_translate` THE SYSTEM SHALL 要求 Gemini 输出源语言文本，再通过所选文本 LLM Profile 生成目标译文。
- **R8.5** WHEN 处理模式为 `bilingual_once` THE SYSTEM SHALL 要求 Gemini 同时输出结构化源文和译文；缺少任意一项均视为失败。
- **R8.6** THE SYSTEM SHALL 默认限制 Gemini 单次调用为 60 秒；超过上限的长片段 SHALL 按 SubForge 自产语音区间（ffmpeg silencedetect）自动切块逐段识别并拼回绝对时间轴，单段语音超限时均匀切分，检测失败时回退整段一次识别并附带警告，而不是拒绝请求。
- **R8.7** THE SYSTEM SHALL 允许配置源语言、模型名、识别提示词、代理、TLS 校验和 CA bundle。
- **R8.8** THE SYSTEM SHALL 对 HTTP 成功但内容为空、语义为空或格式错误执行有界重试；重试耗尽后返回安全错误。
- **R8.9** THE SYSTEM SHALL 不把 API Key、Authorization、完整请求音频或敏感 prompt 写入日志、任务事件、HTML、SQLite 或 Library metadata。
- **R8.10** THE SYSTEM SHALL 明确提示 Google AI Pro/Antigravity 订阅不等于 Gemini API 配额，配置测试以实际模型调用结果为准。

### R9. Gemini Profile 与操作选择

- **R9.1** THE SYSTEM SHALL 支持多套命名 Gemini 音频 Profile，以同时配置官方 Google API 与兼容网关。
- **R9.2** WHEN 用户发起片段重处理 THE SYSTEM SHALL 允许选择片段处理器、Profile 和处理模式；Profile 可以提供默认处理模式，但操作时允许覆盖。
- **R9.3** WHEN Gemini Profile 缺少可用 Key、Base URL 或模型名 THE SYSTEM SHALL fail closed，并在发送音频前拒绝请求。
- **R9.4** WHEN 用户测试 Gemini Profile THE SYSTEM SHALL 通过与实际片段处理相同的传输 Adapter 验证鉴权、模型存在性和音频输入能力，而非只调用模型列表接口。

### R10. UI 与状态

- **R10.1** THE SYSTEM SHALL 在现有播放器字幕列表内提供校正和片段重处理入口，不要求用户离开播放上下文。
- **R10.2** WHILE 片段重处理运行 THE SYSTEM SHALL 显示截取、识别、翻译和候选完成状态，并允许取消。
- **R10.3** THE SYSTEM SHALL 将片段重处理任务与整条 Track 处理任务区分展示，局部失败不得把整个 Track 标记为 failed。
- **R10.4** WHEN 候选已生成但尚未确认 THE SYSTEM SHALL 将其视为临时状态；页面刷新后可以安全丢弃或显式恢复，但不得当作正式字幕。
