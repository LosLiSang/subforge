# Base Auto Subtitle — Requirements

## 背景与目标

为 ASMR / 同人音声爱好者提供一键式字幕自动生成工具。输入日语为主的音频/视频文件，自动完成语音识别（ASR）生成源语言字幕，再借助 LLM 进行上下文感知翻译，输出目标语言字幕。

v0.1 以 CLI 形态交付，优先跑通核心流程，为后续 GUI 打基础。

## 范围

- In scope:
  - 本地 ASR 引擎（faster-whisper）将语音转写为源语言字幕
  - LLM 驱动的上下文感知翻译（参考 GPT-Subtrans 的上下文窗口策略）
  - 多文件并发处理与队列调度
  - CLI 接口
  - PotPlayer 兼容的字幕输出（SRT / VTT）
- Out of scope:
  - GUI 界面
  - 说话人分离（speaker diarization）
  - 字幕编辑器 / 校对交互界面
  - 云端 ASR 兜底（留待后续版本评估）

## 需求（EARS）

### R1. 文件输入
- **R1.1** WHEN 用户通过 CLI 提交一个或多个文件路径 THE SYSTEM SHALL 扫描并识别支持的格式（mp3 / mp4 / wav / m4a / flac），过滤不支持的文件并给出提示。
- **R1.2** WHEN 用户提交的是目录路径 THE SYSTEM SHALL 递归扫描该目录下所有受支持的媒体文件。

### R2. ASR 语音识别
- **R2.1** WHEN 媒体文件进入处理 THE SYSTEM SHALL 调用 faster-whisper 模型将语音转写为源语言字幕（默认日语），并为每条字幕生成精确的起止时间戳。模型文件存放于 `~/.subforge/models/`。
- **R2.2** IF 用户未指定模型大小 THEN THE SYSTEM SHALL 使用 medium 作为默认模型。
- **R2.3** WHERE 用户指定了源语言 THE SYSTEM SHALL 跳过语言自动检测，直接使用指定语言进行转写。
- **R2.4** WHEN ASR 转写完成 THE SYSTEM SHALL 输出一份源语言 SRT 文件，与源文件同名、同目录。

### R3. LLM 上下文感知翻译
- **R3.1** WHEN 源语言字幕生成完成 THE SYSTEM SHALL 将字幕条目按批次提交给 LLM 进行翻译，每批次携带前后若干条字幕作为上下文窗口。
- **R3.2** WHEN 翻译进行中 THE SYSTEM SHALL 维护一个滑动上下文窗口，使相邻批次共享部分字幕条目的译文，确保术语和语体的一致性。
- **R3.3** IF 用户未指定目标语言 THEN THE SYSTEM SHALL 默认翻译为简体中文。
- **R3.4** WHERE 用户指定了目标语言 THE SYSTEM SHALL 翻译为对应语言。
- **R3.5** WHEN 翻译完成 THE SYSTEM SHALL 输出一份目标语言 SRT 文件，与源文件同名、同目录，文件名加目标语言后缀（如 `_zh.srt`）。
- **R3.6** WHERE LLM API 调用失败（超时、限流、鉴权错误）THE SYSTEM SHALL 按指数退避重试最多 3 次，3 次均失败则标记该文件翻译失败并记录错误信息。
- **R3.7** WHERE LLM provider 为 OpenAI 兼容 API 时 THE SYSTEM SHALL 正常工作；首期不支持其他 provider（Anthropic、Ollama 等留待后续扩展）。

### R4. 并发与队列
- **R4.1** WHEN 用户提交 N 个文件 THE SYSTEM SHALL 并行处理 M 个文件（M 可配置，默认 2），其余文件进入等待队列。
- **R4.2** WHEN 队列中某个文件开始处理 THE SYSTEM SHALL 先完成 ASR 阶段，再进入翻译阶段（同一文件内两阶段串行，不同文件之间并行）。
- **R4.3** WHEN 一个文件处理完成（成功或最终失败）THE SYSTEM SHALL 自动从队列中取出下一个文件开始处理。
- **R4.4** WHILE 队列中仍有文件等待处理 THE SYSTEM SHALL 持续展示队列状态（排队数 / 处理中 / 已完成 / 失败）。

### R5. CLI 接口
- **R5.1** WHEN 用户执行 CLI 命令 THE SYSTEM SHALL 接受以下参数：
  - 输入路径（文件或目录，必填，支持多个）
  - `--model`：ASR 模型大小（tiny/base/small/medium/large，默认 medium）
  - `--source-lang`：源语言（默认 ja）
  - `--target-lang`：目标语言（默认 zh）
  - `--concurrency`：最大并行数（默认 2）
  - `--llm-api-key`：LLM API 密钥（支持环境变量 `LLM_API_KEY`）
  - `--llm-base-url`：LLM API 地址（支持环境变量 `LLM_BASE_URL`）
  - `--llm-model`：LLM 模型名（支持环境变量 `LLM_MODEL`）
  - `--output-dir`：输出目录（默认与源文件同目录）
- **R5.2** WHEN 处理全部结束 THE SYSTEM SHALL 打印汇总：成功数、失败数、各文件耗时。
- **R5.3** WHEN 用户执行 `--help` 或 `-h` THE SYSTEM SHALL 显示完整帮助信息。

### R6. 进度与日志
- **R6.1** WHILE 每个文件处理中 THE SYSTEM SHALL 实时输出当前阶段（ASR 进度百分比 / 翻译进度百分比）。
- **R6.2** WHEN 发生错误 THE SYSTEM SHALL 输出到 stderr 并继续处理剩余文件，不中断整个批次。

## 验收场景（Given-When-Then）

### S1. 单个日语 MP3 完整流程 ← R1.1, R2.1, R3.1, R3.3
- **Given** 一个日语 ASMR 音频文件 `work.mp3`
- **When** 用户执行 `base-auto-subtitle work.mp3`
- **Then** 程序调用 faster-whisper medium 模型进行转写，生成 `work.srt`（日语），再调用 LLM 翻译为简体中文，生成 `work_zh.srt`

### S2. 多文件并发与队列 ← R4.1–R4.4
- **Given** 4 个 mp3 文件，`--concurrency 2`
- **When** 用户提交这 4 个文件
- **Then** 2 个文件立即开始并行处理（ASR → 翻译），另外 2 个排队；当某个文件完成后，队列中下一个自动开始；最终 4 个文件均生成对应 SRT

### S3. 自定义语言与模型 ← R2.3, R3.4
- **Given** 英语音频文件 `lecture.mp3`
- **When** 用户执行 `base-auto-subtitle lecture.mp3 --source-lang en --target-lang zh --model large`
- **Then** 使用 large 模型以英语转写，翻译为中文

### S4. LLM 翻译失败重试 ← R3.6
- **Given** LLM API 暂时不可用
- **When** 翻译批次请求失败
- **Then** 程序按指数退避重试最多 3 次；3 次均失败则报错到 stderr 并标记该文件翻译失败，继续处理其他文件

## 非功能需求

- **性能**：单个 1 小时音频的 ASR 转写在 GPU 上应在 5 分钟内完成（medium 模型）
- **兼容性**：Windows 优先（目标用户群），macOS / Linux 可运行但非必须
- **翻译质量**：LLM 上下文窗口策略需参考 GPT-Subtrans，保证相邻字幕术语一致、语体连贯
- **资源限制**：并行数不应超过 GPU 显存承受能力，默认值 2 为保守设定

## 参考项目

- [GPT-Subtrans](https://github.com/machinewrapped/gpt-subtrans)：LLM 上下文感知字幕翻译的参考实现
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)：CTranslate2 加速的 Whisper 推理

## 未决问题

- ~~❓ LLM provider 首期只支持 OpenAI 兼容 API，还是也需要支持其他（如 Anthropic、本地 Ollama）？~~
  → **已确认**：首期仅支持 OpenAI 兼容 API，后续按需扩展。
- ~~❓ 是否需要字幕时间轴微调功能（如合并过短的字幕条目）？~~
  → **已确认**：可以有，但优先级低于核心流程，延后实现。
- ~~❓ ASR 模型文件存放路径如何约定？~~
  → **已确认**：模型文件存放于用户目录下的 `~/.subforge/models/` 中。
