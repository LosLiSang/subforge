# Deepgram ASR Provider — Requirements

## 背景与目标

SubForge 当前只支持本地 faster-whisper ASR。实测 `music/BV1dogCzbEBu.mp3` 的 3 分钟样本后，Deepgram Nova-3 在日语可读性、标点和部分错词修正上优于现有本地结果。该功能目标是在保持默认本地 ASR 行为不变的前提下，为用户增加 Deepgram 云端 ASR 选项，并继续复用现有时间轴后处理、翻译、断点续跑和 SRT 输出流程。

## 范围

- In scope:
  - 用户可在本地 ASR 和 Deepgram 云端 ASR 之间选择
  - Deepgram 默认使用 `nova-3`
  - Deepgram 使用现有源语言配置作为转写语言提示
  - Deepgram API key 可通过环境变量或配置文件提供
  - Deepgram 支持 keyterm 配置，用于提升专有词、角色名和易错词识别
  - Deepgram 输出转换为现有 `SubtitleEntry` 数据结构
  - Deepgram ASR 结果继续进入现有 timeline、翻译和 SRT 输出流程
  - Deepgram 失败时给出明确错误，不泄露 API key
- Out of scope:
  - Deepgram 实时流式 ASR
  - 多云 ASR 自动择优
  - Deepgram diarization / speaker labels
  - Deepgram detect_language 默认启用
  - GUI 配置界面
  - 自动从 LLM 生成 keyterm

## 需求(EARS)

### R1. ASR Provider 选择

- **R1.1** WHEN 用户未指定 ASR provider THE SYSTEM SHALL 继续使用现有本地 faster-whisper ASR。
- **R1.2** WHEN 用户指定 ASR provider 为 Deepgram THE SYSTEM SHALL 使用 Deepgram 云端 ASR 转写媒体文件。
- **R1.3** IF 用户指定了不支持的 ASR provider THEN THE SYSTEM SHALL 拒绝启动并显示可理解的错误。
- **R1.4** WHEN 用户查看 CLI 帮助 THE SYSTEM SHALL 显示 ASR provider 选项及可选值。

### R2. Deepgram 配置

- **R2.1** WHEN Deepgram provider 被启用 THE SYSTEM SHALL 使用 Deepgram API key 进行认证。
- **R2.2** IF Deepgram provider 被启用且 API key 缺失 THEN THE SYSTEM SHALL 标记该文件处理失败并提示用户配置 API key。
- **R2.3** WHERE 环境变量提供 Deepgram API key THE SYSTEM SHALL 使用该环境变量作为认证来源。
- **R2.4** WHERE 配置文件提供 Deepgram API key THE SYSTEM SHALL 在环境变量未提供时使用配置文件值。
- **R2.5** WHEN 日志记录 Deepgram 调用 THE SYSTEM SHALL 不输出完整 API key。

### R3. Deepgram 模型与语言

- **R3.1** WHEN Deepgram provider 被启用且用户未指定 Deepgram 模型 THE SYSTEM SHALL 使用 `nova-3`。
- **R3.2** WHERE 用户配置了 Deepgram 模型 THE SYSTEM SHALL 使用该模型发起转写。
- **R3.3** WHEN Deepgram provider 发起转写 THE SYSTEM SHALL 使用当前源语言配置作为语言提示。
- **R3.4** IF 用户未指定源语言 THEN THE SYSTEM SHALL 继续使用现有默认源语言。
- **R3.5** WHERE 用户配置了 Deepgram keyterm THE SYSTEM SHALL 将 keyterm 传递给 Deepgram 以提升指定术语识别。

### R4. 转写结果兼容

- **R4.1** WHEN Deepgram 返回带时间戳的转写结果 THE SYSTEM SHALL 将结果转换为现有 `SubtitleEntry` 列表。
- **R4.2** WHEN Deepgram 转写完成 THE SYSTEM SHALL 继续执行现有时间轴后处理。
- **R4.3** WHEN Deepgram 转写完成 THE SYSTEM SHALL 写出源语言 SRT。
- **R4.4** WHEN Deepgram 源语言 SRT 写出后 THE SYSTEM SHALL 继续执行现有 LLM 翻译流程。
- **R4.5** WHEN Deepgram 返回空转写结果 THE SYSTEM SHALL 将该文件标记失败并记录原因。

### R5. 断点续跑兼容

- **R5.1** WHEN 已存在完整目标语言 SRT THE SYSTEM SHALL 按现有断点续跑规则跳过整个文件，不调用 Deepgram。
- **R5.2** WHEN 已存在有效源语言 SRT THE SYSTEM SHALL 按现有断点续跑规则跳过 ASR，不调用 Deepgram。
- **R5.3** WHERE 用户启用强制从头开始 THE SYSTEM SHALL 忽略已有 SRT 和断点，并按当前 ASR provider 重新转写。
- **R5.4** IF 断点状态的 ASR provider 或 Deepgram 关键配置与当前配置不匹配 THEN THE SYSTEM SHALL 不复用该断点状态。

### R6. 错误处理

- **R6.1** IF Deepgram API 返回认证错误 THEN THE SYSTEM SHALL 标记当前文件失败并提示认证失败。
- **R6.2** IF Deepgram API 返回限流或临时服务错误 THEN THE SYSTEM SHALL 重试后仍失败再标记当前文件失败。
- **R6.3** IF Deepgram API 调用失败 THE SYSTEM SHALL 继续处理批量任务中的其它文件。
- **R6.4** WHEN Deepgram API 调用失败 THE SYSTEM SHALL 记录足够排查的信息，但不得泄露 API key。

## 验收场景(Given-When-Then)

### S1. 默认仍使用本地 ASR ← R1.1

- **Given** 用户未指定 ASR provider
- **When** 用户执行 `subforge audio.mp3`
- **Then** 系统使用现有 faster-whisper ASR 流程

### S2. 使用 Deepgram Nova-3 转写 ← R1.2, R3.1, R4.1

- **Given** 用户已配置 Deepgram API key
- **When** 用户执行 `subforge audio.mp3 --asr-provider deepgram`
- **Then** 系统使用 Deepgram `nova-3` 转写音频，并生成源语言 SRT

### S3. Deepgram key 缺失 ← R2.2, R6.3

- **Given** 用户未配置 Deepgram API key
- **When** 用户执行 `subforge audio.mp3 --asr-provider deepgram`
- **Then** 当前文件处理失败，日志提示缺少 Deepgram API key，批量任务中的其它文件继续处理

### S4. Deepgram keyterm 生效路径 ← R3.5

- **Given** 用户在配置文件中配置了 Deepgram keyterm
- **When** 用户使用 Deepgram provider 转写
- **Then** 系统将 keyterm 传递给 Deepgram API

### S5. 源 SRT 断点跳过 Deepgram ← R5.2

- **Given** 媒体文件旁已有有效源语言 SRT
- **When** 用户执行 `subforge audio.mp3 --asr-provider deepgram`
- **Then** 系统复用源语言 SRT，不调用 Deepgram

### S6. 强制重跑调用 Deepgram ← R5.3

- **Given** 媒体文件旁已有源语言 SRT 和目标语言 SRT
- **When** 用户执行 `subforge audio.mp3 --asr-provider deepgram --force`
- **Then** 系统忽略已有字幕并调用 Deepgram 重新转写

## 非功能需求

- **兼容性**：默认行为不变，未启用 Deepgram 时不要求 Deepgram API key。
- **安全性**：日志、错误消息和断点状态不得保存或输出完整 Deepgram API key。
- **可靠性**：Deepgram 临时错误应重试，单文件失败不得中断批量任务。
- **可测试性**：Deepgram API 调用必须可通过 mock 覆盖，不依赖真实网络完成单元测试。
- **成本控制**：测试和文档应提示用户云端 ASR 会产生 API 费用。

## 未决问题

- 无。
