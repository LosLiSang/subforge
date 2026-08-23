# Changelog

本文件记录 SubForge 的显著变更。版本号遵循 [Semantic Versioning](https://semver.org/)，格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [0.5.0] - Unreleased

### Added
- **创作者实体**：社团/声优作为可复用实体，内部 ID 区分同名记录；RJ 作品可关联多社团/声优，直播归档仅关联声优。支持创建/编辑/合并/删除，作品详情可按创作者筛选。
- **导入来源**：URL 导入产生不可变记录（保留原始链接），可查看/打开但不覆盖。
- **RJ 文件夹导入**：递归扫描作品目录，将支持音频作为 Track 导入，常见视频转 M4A AAC；批次允许部分成功，原文件永不移动/修改/删除。
- **下载/任务中心页**：统一展示媒体下载、媒体导入、ASR、翻译、排队、限流重试、完成/失败/取消状态，含进度与出错原因。
- **URL 导入封面抓取**：异步拉取 cover art 并缓存。
- **跨进程翻译全局限流**：`TranslationRequestLimiter` 以锁文件 semaphore 限制并发出去请求，防止多 Worker 同时打爆 LLM provider。

### Changed
- **LLM 重试语义**：仅对瞬时错误重试（429 / 502 / 503 / 504；401 与 500 不重试）；`Retry-After` 同时支持秒数与 HTTP date；最后一次失败不再无谓 sleep。
- **语义空响应处理**：reasoning 吃满预算或未按 `[N]` 前缀输出时，改为最多 3 次语义重试并串行化，绝不把全空批次当作成功缓存。
- **无语音终态**：ASR 未产生可用字幕段时进入 `no_speech`（`TASK_NO_SPEECH` 事件），不再抛 `RuntimeError`；可播放并允许调整后重处理。
- **任务自动重试（进展为锚）**：连续无进展失败累计达到上限才彻底置为 failed；取得进展即重置计数，成功或 `no_speech` 即结束。
- **重启恢复语义**：应用重启后恢复 queued/running 任务（而非整体标记 interrupted），并清理旧的终态历史。

### Fixed
- `_get_retry_after` 支持 HTTP-date 格式，修复部分 429 响应重试等待解析失败的问题。
- 修正最终一次重试后仍会额外 sleep 的无效等待。

## [0.4.0] - 2026-08-23

上一版已验证基线。此前功能与库 UI（Slice 0–3）已随各提交落地，本次未改动语义；归档此版本以保留可回溯基线。
