# Library UI — Tasks

## Slice 0：基础契约

- [x] **T0.1 新字幕语言后缀契约** ← R1
  - 红：CLI/编排测试期望 `audio.ja.srt`、`audio.zh.srt` 且 legacy 不被复用。
  - 绿：新增统一 `subtitle_path()` 并同步 orchestrator、resume、README、测试。
- [x] **T0.2 结构化处理事件 seam** ← R2
  - 红：通过公开 `event_sink` 断言成功、失败、恢复流程事件和顺序。
  - 绿：新增事件模型/发布器并接入 process_one/process_all/translate progress。
- [x] **T0.3 Worker JSONL Adapter 骨架** ← R2.5
  - 红：给可控处理函数时 stdout 每行是安全 JSON 事件。
  - 绿：实现 worker 请求模型与 JSONL sink；真实子进程调度留 Slice 2。

## Slice 1：Library

- [x] **T1.1 Library 初始化与可迁移元数据** ← R3, R4.1, R4.6
- [x] **T1.2 单音频安全复制与 SHA-256 去重** ← R5
- [x] **T1.3 RJ 唯一、重复 RJ 合并多 Track、直播归档身份** ← R4
- [x] **T1.4 SQLite 索引与删除后重建** ← R6
- [x] **T1.5 原生选择器 Adapter 与活动 Library 配置** ← R3.1, R7.5

## Slice 2：工作台

- [x] **T2.1 默认 UI 依赖、`subforge ui` 与 localhost 启动** ← R7.1
- [x] **T2.2 启动令牌、会话、CSRF、Host/Origin 防护** ← R7.2–R7.4
- [x] **T2.3 Library 列表、导入表单和详情页** ← R3–R6
- [x] **T2.4 LLM Profiles、密钥掩码和设置页** ← R8
- [x] **T2.5 独立 Worker 子进程与默认单媒体队列** ← R9
- [x] **T2.6 SQLite 状态 + SSE 进度，刷新/重启恢复** ← R9.5
- [x] **T2.7 继续、重新翻译、从头处理和取消** ← R10

## Slice 3：播放器闭环

- [x] **T3.1 Track 媒体 ID 路由与 HTTP Range** ← R11.1, R11.2
- [x] **T3.2 `.ja.srt` / `.zh.srt` JSON 路由** ← R11.3, R11.4
- [x] **T3.3 原生音频播放器与双语字幕同步** ← R11
- [x] **T3.4 `.trash` 软删除** ← R12.1
- [x] **T3.5 闭环 E2E、索引重建与 Library 迁移验证** ← 全部

## 交付验收

- [ ] 全量 pytest 通过，新增测试只穿过已确认 seam。
- [ ] sdist/wheel 不包含用户媒体、Library、SQLite、密钥或调试数据。
- [ ] 干净虚拟环境完整安装后 `subforge ui` 可启动。
- [ ] 空闲主进程内存测量记录在验证输出中并低于 200MB。
