# Library UI — Requirements

## 背景与目标

SubForge 当前以 CLI 完成 ASR 与翻译，但核心用户需要一个 Windows-first 的本地工作台，用于安全导入音频、查看处理进度、恢复失败任务并播放中日双语字幕。第一版闭环做到单音频 Track；数据模型从第一天支持一个 Library Item 拥有多个 Track。

## 范围

### In scope（Slice 0–3）

- 统一 CLI/UI 字幕命名为 `<媒体名>.<ISO 语言代码>.srt`
- 处理核心发布结构化事件，CLI 和 UI 共用同一管线
- 一个活动 Library、首次启动选择根目录、Library 可整体迁移
- RJ 作品和直播归档两种 Item，稳定 Item ID / Track ID
- 单音频复制归档、流式 SHA-256、内容去重、原文件不修改不删除
- `metadata.json` 为事实来源，SQLite 为可重建索引
- localhost-only UI、启动令牌、会话 Cookie、CSRF、Origin/Host 校验
- Windows 原生文件/目录选择器
- 命名 LLM Profiles、密钥掩码与任务配置快照
- 单媒体 Worker 子进程队列、结构化进度、取消/继续/重译/从头处理
- 音频 Range 服务、中日 SRT 解析与同步播放器
- `.trash` 软删除

### Out of scope

- 旧 `audio.srt` / `audio_zh.srt` 与旧断点兼容或迁移
- RJ 文件夹整包导入与 DLsite 刮削
- 视频抽音频与缩略图
- 公网/局域网访问、多用户、账号系统
- 网页内字幕编辑
- 多目标语言、永久清空回收站、实时文件监听

## 需求（EARS）

### R1. 字幕文件契约（Slice 0）

- **R1.1** WHEN 系统为媒体生成源语言字幕 THE SYSTEM SHALL 写入 `<stem>.<source-language>.srt`。
- **R1.2** WHEN 系统为媒体生成翻译字幕 THE SYSTEM SHALL 写入 `<stem>.<target-language>.srt`。
- **R1.3** WHEN 系统恢复已有字幕 THE SYSTEM SHALL 只识别新语言后缀契约，不读取或迁移旧命名。
- **R1.4** WHEN 用户通过 `--output-dir` 指定目录 THE SYSTEM SHALL 在该目录使用同一命名契约。

### R2. 处理事件（Slice 0）

- **R2.1** WHEN 一个任务进入处理管线 THE SYSTEM SHALL 依序发布排队、ASR、翻译和最终状态的结构化事件。
- **R2.2** WHILE ASR 或翻译推进 THE SYSTEM SHALL 发布可机器读取的进度值，而不是要求调用方解析日志。
- **R2.3** IF 处理失败 THEN THE SYSTEM SHALL 发布包含阶段、错误类型和安全消息的失败事件。
- **R2.4** WHERE 调用方未提供事件订阅器 THE SYSTEM SHALL 保持现有批处理行为。
- **R2.5** WHEN CLI 调用处理核心 THE SYSTEM SHALL 通过 CLI 事件适配器呈现进度；WHEN UI Worker 调用处理核心 THE SYSTEM SHALL 输出 JSON Lines 事件。

### R3. Library 初始化与迁移（Slice 1）

- **R3.1** WHEN 用户第一次运行 `subforge ui` 且没有活动 Library THE SYSTEM SHALL 要求通过原生目录选择器选择 Library 根目录。
- **R3.2** WHEN Library 初始化 THE SYSTEM SHALL 创建 `library.json`、`works/`、`streams/`、`.incoming/`、`.trash/` 和 `.subforge/`。
- **R3.3** WHEN 整个 Library 被移动到另一磁盘并重新选择 THE SYSTEM SHALL 仅凭相对路径和文件系统元数据恢复内容。
- **R3.4** WHERE 配置了多个根目录 THE SYSTEM SHALL 一次只打开一个活动 Library。

### R4. Item 与 Track 模型（Slice 1）

- **R4.1** WHEN 创建任何 Item THE SYSTEM SHALL 分配稳定 Item ID、`schema_version` 和类型 `rj_work|stream_archive`。
- **R4.2** WHEN 导入媒体 THE SYSTEM SHALL 分配稳定 Track ID，并保留原媒体文件名。
- **R4.3** IF 类型是 RJ 作品 THEN THE SYSTEM SHALL 要求有效 RJ 号，且当前 Library 内唯一。
- **R4.4** IF 类型是直播归档 THEN THE SYSTEM SHALL 要求作者/博主；目录使用人类可读名称和稳定短 ID。
- **R4.5** WHEN 相同 RJ 号导入不同内容 THE SYSTEM SHALL 把它作为新 Track 合并到既有 Item。
- **R4.6** WHEN 元数据写入 THE SYSTEM SHALL 使用临时文件、flush 和原子替换，避免产生半个 JSON。

### R5. 安全导入（Slice 1）

- **R5.1** WHEN 用户选择音频导入 THE SYSTEM SHALL 复制到 `.incoming`，复制过程中流式计算 SHA-256，再原子提升到正式目录。
- **R5.2** THE SYSTEM SHALL 永不移动、覆盖或删除导入源文件。
- **R5.3** IF Library 已包含相同 SHA-256 THE SYSTEM SHALL 不再复制，并返回既有 Item/Track。
- **R5.4** IF 导入中断 THEN THE SYSTEM SHALL 保留可理解的中断状态；重试时从头复制。
- **R5.5** WHEN 复制完成且元数据有效 THE SYSTEM SHALL 立即把 Item 展示为“等待处理”，不等待翻译成功。

### R6. 文件系统真相与索引（Slice 1）

- **R6.1** THE SYSTEM SHALL 把 `metadata.json`、媒体、字幕和 Track resume 文件视为长期资产。
- **R6.2** THE SYSTEM SHALL 仅把 SQLite 用作可重建搜索索引和运行时任务状态。
- **R6.3** IF SQLite 缺失或损坏 THEN THE SYSTEM SHALL 扫描 `metadata.json` 自动完整重建。
- **R6.4** WHEN UI 启动 THE SYSTEM SHALL 快速加载索引并后台增量扫描；WHEN 用户请求重扫 THE SYSTEM SHALL 手动同步外部变化。

### R7. 本地 UI 安全（Slice 2）

- **R7.1** WHEN `subforge ui` 启动 THE SYSTEM SHALL 只监听 `127.0.0.1`，且不提供 `0.0.0.0` 开关。
- **R7.2** WHEN UI 启动 THE SYSTEM SHALL 生成一次性启动令牌，换取 SameSite 会话 Cookie 后立即从 URL 移除令牌。
- **R7.3** WHEN 执行任何写操作 THE SYSTEM SHALL 校验会话、CSRF、Host 和 Origin。
- **R7.4** THE SYSTEM SHALL 通过 Item/Track ID 提供媒体访问，不提供任意路径读取接口。
- **R7.5** WHEN 用户点击选择文件或目录 THE SYSTEM SHALL 由后端调用 Windows 原生选择器；浏览器不提交任意磁盘路径。

### R8. LLM Profiles 与密钥（Slice 2）

- **R8.1** THE SYSTEM SHALL 支持多套命名 OpenAI-compatible LLM Profile。
- **R8.2** WHEN UI 展示由 SubForge 管理且长度至少 12 的 Key THE SYSTEM SHALL 仅展示前 4、后 4 字符；短 Key 只显示“已配置”。
- **R8.3** IF Key 来自环境变量 THEN THE SYSTEM SHALL 只显示“已通过环境变量配置”。
- **R8.4** THE SYSTEM SHALL 不在 HTML、JSON、SSE、SQLite、任务事件、metadata 或日志中输出完整 Key。
- **R8.5** WHEN Key 输入留空提交 THE SYSTEM SHALL 保持原值；删除 Key 必须使用独立确认操作。

### R9. 任务队列与 Worker（Slice 2）

- **R9.1** WHEN 用户开始处理 Track THE SYSTEM SHALL 冻结 ASR 后端、场景、Whisper 模型和 LLM Profile ID 的配置快照。
- **R9.2** THE SYSTEM SHALL 默认同时运行一个媒体 Worker，并允许高级设置提高媒体并发并提示资源风险。
- **R9.3** WHEN Worker 启动 THE SYSTEM SHALL 在独立子进程运行 ASR/翻译并通过 JSON Lines 输出结构化事件。
- **R9.4** WHEN Worker 完成或失败 THE SYSTEM SHALL 退出并释放模型内存/显存；UI 主进程不得加载 ASR 模型。
- **R9.5** WHEN 页面刷新或 UI 重启 THE SYSTEM SHALL 从 SQLite/文件系统恢复任务状态；原运行态转为“处理中断”。
- **R9.6** WHEN 用户取消任务 THE SYSTEM SHALL 先请求正常停止，超时后终止 Worker，并保留可恢复产物。

### R10. 继续、重译与从头处理（Slice 2）

- **R10.1** WHEN 用户选择“继续处理” THE SYSTEM SHALL 使用原配置快照并复用已有 ASR 和翻译批次。
- **R10.2** WHEN 用户选择“重新翻译” THE SYSTEM SHALL 保留源字幕，备份/清理目标字幕与翻译断点，并允许切换 LLM Profile。
- **R10.3** WHEN 用户选择“从头处理” THE SYSTEM SHALL 备份生成字幕、清除 ASR/翻译断点并重新 ASR，但绝不修改媒体。
- **R10.4** WHEN Library Track 保存断点 THE SYSTEM SHALL 写入 Item 内 `.subforge/tracks/<track-id>.resume.json`，以 Track ID 和相对路径作为可迁移身份。

### R11. 播放器（Slice 3）

- **R11.1** WHEN 用户打开可播放 Track THE SYSTEM SHALL 使用浏览器原生音频播放器播放 Library 媒体。
- **R11.2** THE SYSTEM SHALL 支持 HTTP Range 请求以便跳转和继续播放。
- **R11.3** WHEN `.ja.srt` / `.zh.srt` 存在 THE SYSTEM SHALL 解析为结构化字幕并随播放时间同步高亮。
- **R11.4** IF 无字幕、只有源字幕或翻译失败 THEN THE SYSTEM SHALL 明确显示对应状态且播放器仍可使用。

### R12. 软删除与资源预算（Slice 3）

- **R12.1** WHEN 用户把 Item 移出 Library THE SYSTEM SHALL 中止任务并把整个目录原子移动到 `.trash`，不永久删除。
- **R12.2** WHILE UI 空闲 THE SYSTEM SHALL 以 `< 200MB` 主进程内存为目标；浏览器和处理 Worker 不计入该预算。

## 验收场景

- **S1 新字幕契约**：CLI 处理 `audio.m4a` 后只生成 `audio.ja.srt`、`audio.zh.srt`。
- **S2 单文件闭环**：新 Library 导入一个 RJ 音频后立即显示等待处理，完成后可播放双语字幕。
- **S3 内容去重**：同一内容换名再次导入不复制，并打开既有 Track。
- **S4 页面刷新**：处理中的页面刷新后仍显示持久化进度。
- **S5 索引重建**：删除 SQLite 后重启，作品和播放器从 metadata 自动恢复。
- **S6 Library 迁移**：整体换盘并重新选择后媒体、字幕和断点仍可使用。
- **S7 安全**：无会话/CSRF、错误 Origin、任意路径请求均被拒绝。
- **S8 软删除**：移出 Library 后 Item 不再显示，目录存在于 `.trash` 且可人工恢复。

## 测试 seam

测试只通过以下公开 interface：

1. CLI 调用及其文件产物。
2. 处理函数的事件订阅 interface。
3. `LibraryStore` 的初始化、导入、扫描、查询和软删除 interface。
4. Starlette ASGI interface（HTTP/SSE/Range），外部 ASR/LLM 和原生选择器使用 Adapter 替换。
