# SubForge v0.2 优化 — Requirements

## 背景与目标

v0.1 已跑通 ASR → 翻译核心流程，但存在四个用户体验与性能瓶颈：(1) 无进度条，处理长音频时用户无法感知进度；(2) 单个文件内翻译批次串行执行，LLM API 往返延迟被放大；(3) 仅靠 `print()` 输出到 stderr，无结构化日志可用于排错；(4) ASR 模型每次启动都尝试向 HuggingFace Hub 请求，即使本地已有模型文件。

v0.2 聚焦这四项优化，不改动核心流程架构。

## 范围

- In scope:
  - tqdm 进度条（ASR 每文件一条，翻译每文件一条，独立显示）
  - 翻译批次并行化（单文件内多批次并发，并发数在 TOML 配置文件中控制）
  - 结构化日志（Python logging 模块，默认 INFO 级别，同时输出 stderr 和 `subforge.log` 文件）
  - 本地模型缓存检测（faster-whisper 模型文件已存在时跳过 HF Hub 下载）
- Out of scope:
  - 多文件之间的翻译并行度调整（已有 `concurrency` 控制）
  - GUI、字幕编辑器、说话人分离
  - 新的 LLM provider 支持
  - 翻译后的质量校验 / 后编辑

## 需求（EARS）

### R1. 进度条

- **R1.1** WHEN 单个文件进入 ASR 阶段 THE SYSTEM SHALL 为该文件显示一条 tqdm 进度条，实时反映转写进度百分比。
- **R1.2** WHEN 单个文件进入翻译阶段 THE SYSTEM SHALL 为该文件显示一条新的 tqdm 进度条，实时反映已完成翻译的批次数占总批次数比例。
- **R1.3** WHILE ASR 或翻译进行中 THE SYSTEM SHALL 在进度条上显示当前阶段名称（"ASR" / "Translate"）及文件名。
- **R1.4** WHEN ASR 阶段完成 THE SYSTEM SHALL 将对应进度条标记为 100% 并关闭；翻译进度条同理。
- **R1.5** WHEN 并发处理多个文件 THE SYSTEM SHALL 为每个活跃文件的当前阶段各自维护一条独立的进度条，多条进度条在终端中同时可见、互不覆盖。

### R2. 翻译批次并行化

- **R2.1** WHEN 单个文件的字幕批次需要翻译 THE SYSTEM SHALL 同时翻译 N 个批次（N 为翻译并发度，在 `[translate]` TOML 配置段中设定，默认值 8）。
- **R2.2** WHILE 多个批次并发翻译中 THE SYSTEM SHALL 保证每个批次的上下文窗口（`prev_context`）由已完成批次的实际译文构成，不得使用空占位或猜测值。
- **R2.3** IF 翻译并发度设为 1 THEN THE SYSTEM SHALL 退化为串行行为，与 v0.1 行为一致。
- **R2.4** WHILE 并行翻译进行中 THE SYSTEM SHALL 保证翻译结果的顺序与原始字幕条目顺序一致（按 entry.index 排序后写入 SRT）。

### R3. 结构化日志

- **R3.1** WHEN 程序启动 THE SYSTEM SHALL 初始化 Python `logging` 模块，默认日志级别为 INFO。
- **R3.2** WHILE 程序运行 THE SYSTEM SHALL 将 WARNING 及以上级别日志同时输出到 stderr 和 `subforge.log` 文件；INFO 及以上级别日志同时输出到 stderr 和 `subforge.log` 文件；DEBUG 日志仅输出到 `subforge.log` 文件。
- **R3.3** WHERE 用户通过 TOML 配置或 CLI 参数指定了日志级别 THE SYSTEM SHALL 以该级别运行（CLI 优先级高于 TOML）。
- **R3.4** WHEN 异常发生 THE SYSTEM SHALL 使用 `logger.exception()` 记录完整 traceback 而非仅 `print()` 错误摘要。
- **R3.5** IF `subforge.log` 文件无法创建或写入 THEN THE SYSTEM SHALL 降级为仅 stderr 输出，不中断处理流程。
- **R3.6** WHERE 日志文件路径未指定 THE SYSTEM SHALL 将 `subforge.log` 写入当前工作目录。

### R4. 本地模型缓存检测

- **R4.1** IF faster-whisper 所需的模型文件已存在于本地模型目录（`~/.subforge/models/`）THEN THE SYSTEM SHALL 直接加载本地模型，不发起任何网络请求。
- **R4.2** IF 模型文件不存在于本地 THEN THE SYSTEM SHALL 按照 faster-whisper 默认行为从 HuggingFace Hub 下载。
- **R4.3** WHEN 检测到本地模型并跳过下载 THE SYSTEM SHALL 记录一条 INFO 级别日志："Model {model_size} found locally, skipping download."。
- **R4.4** WHEN 模型下载开始时 THE SYSTEM SHALL 记录一条 INFO 级别日志，包含模型名称和下载目标路径。
- **R4.5** IF 本地模型文件存在但加载失败（损坏或不完整）THEN THE SYSTEM SHALL 记录 WARNING 日志，并回退到从 HuggingFace Hub 重新下载。

## 验收场景（Given-When-Then）

### S1. ASR 进度条展示 ← R1.1, R1.3, R1.4
- **Given** 一个 30 分钟的日语音频文件 `work.mp3`
- **When** 用户执行 `subforge work.mp3`
- **Then** 终端在 ASR 阶段显示一条 tqdm 进度条，前缀标注 `[ASR] work.mp3`，百分比从 0% 逐步增长到 100%

### S2. 翻译进度条展示 ← R1.2, R1.3, R1.4
- **Given** ASR 阶段已完成，翻译阶段开始
- **When** 翻译进行中
- **Then** 终端显示一条新的 tqdm 进度条，前缀标注 `[Translate] work.mp3`，百分比随完成的批次数增长到 100%

### S3. 多文件并发时进度条不互相覆盖 ← R1.5
- **Given** 3 个音频文件，`concurrency = 2`
- **When** 2 个文件同时在 ASR 阶段
- **Then** 终端同时显示 2 条独立的 tqdm 进度条（或 tqdm 多行模式），各自独立更新，互不覆盖输出

### S4. 并行翻译正确性 ← R2.1, R2.2, R2.4
- **Given** 一个音频文件完成 ASR，生成 60 条字幕，batch_size=20，translate_workers=3
- **When** 翻译阶段执行
- **Then** 三个批次同时提交 LLM API；每个批次的上下文使用已完成的相邻批次译文；最终输出的 SRT 条目顺序与原始字幕顺序一致

### S5. 翻译并发度 = 1 时退回串行 ← R2.3
- **Given** TOML `[translate]` 中 `workers = 1`
- **When** 翻译阶段执行
- **Then** 批次按顺序逐一翻译，行为与 v0.1 完全一致

### S6. 日志输出到文件和终端 ← R3.2
- **Given** 程序正常运行，默认 INFO 级别
- **When** ASR 和翻译过程中产生 INFO 级别事件（如阶段开始、完成）
- **Then** 终端 stderr 和 `./subforge.log` 文件均包含对应日志行

### S7. DEBUG 日志仅写文件 ← R3.2
- **Given** 日志级别设为 DEBUG
- **When** 程序产生 DEBUG 级别日志
- **Then** DEBUG 日志仅出现在 `subforge.log` 中，不出现在 stderr

### S8. 本地模型跳过下载 ← R4.1, R4.3
- **Given** `~/.subforge/models/` 中已存在 faster-whisper medium 模型文件
- **When** 用户执行 ASR
- **Then** 日志显示 "Model medium found locally, skipping download"，加载本地模型，不发起 HF Hub 网络请求

### S9. 模型不存在时正常下载 ← R4.2, R4.4
- **Given** `~/.subforge/models/` 中不存在任何模型文件
- **When** 用户首次执行 ASR
- **Then** 日志显示下载信息，从 HuggingFace Hub 下载模型到本地目录

### S10. 本地模型损坏时回退下载 ← R4.5
- **Given** 本地模型文件存在但已损坏（不完整或被截断）
- **When** 加载本地模型失败
- **Then** 记录 WARNING 日志，回退到从 HuggingFace Hub 重新下载

### S11. 日志文件写入失败时降级 ← R3.5
- **Given** 当前目录无写入权限
- **When** 程序尝试创建 `subforge.log`
- **Then** 日志仅输出到 stderr，程序继续正常处理

## 非功能需求

- **性能**：并行翻译后，单文件翻译总耗时应显著低于串行模式（batch_size=20 时，4 workers 预期耗时减少约 60–75%，受 LLM API 并发限制约束）
- **兼容性**：Windows 优先，macOS / Linux 可运行
- **可靠性**：日志文件写入失败不得中断核心处理流程；模型加载失败有回退路径
- **可观测性**：所有 `print()` 调用替换为 `logging` 调用；日志行含时间戳、级别、模块名

## 未决问题

- ~~❓ 翻译并发度在哪里配置？~~
  → **已确认**：在 TOML `[translate]` 段中增加 `workers` 字段，不在 CLI 暴露。
- ~~❓ 日志默认级别与输出目标？~~
  → **已确认**：默认 INFO，同时输出 stderr 和 `subforge.log` 文件。
- ~~❓ 进度条粒度？~~
  → **已确认**：每个文件一条进度条（ASR），翻译进度每文件独立。
