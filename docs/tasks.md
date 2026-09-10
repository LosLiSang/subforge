# 任务中心与任务状态

任务中心统一展示媒体下载、导入、字幕处理与模型状态。**字幕 Tab 置首**（依次为字幕 / 下载 / 模型），渲染最新 200 条。

## 字幕任务

两类任务共用一套状态机：

=== "整轨处理（full_process）"

    ```text
    queued → running → completed / no_speech
                    ↘ failed（自动重试）
    ```

    - Worker 以子进程运行，原生崩溃不拖垮 UI；崩溃现场写入 `<Library>/.subforge/logs/worker-<task_id>.log`
    - 失败自动重试：连续**无进展**失败累计 3 次才彻底 failed；翻译批次有进展即重置计数
    - 行内操作：排队/运行中可取消，失败可重试（复用同一 task_id，从断点继续）
    - 按快照的 `asr_provider` 归入并发域：`local` 走本地 GPU 信号量，`deepgram` / `model`（Gemini）走网络 API 信号量，两域互不抢占

=== "片段重处理（segment_reprocess）"

    ```text
    queued → running → awaiting_review --接受--> completed
                              ↘ 放弃--> discarded
                    ↘ failed（可手动重试）
    ```

    - 提交立即返回，不阻塞页面；入队前把解析后的时间窗归一化写入 payload
    - 完成后转 `awaiting_review`，行内出现「查看候选 / 放弃候选」
    - 确认时才调用范围替换改动字幕；放弃只改任务状态
    - **失败或取消均可手动重试**：复用同一 task_id + 原 payload 重新入队，重试前校验引用的翻译/音频配置仍在（已删除则拒绝并提示）；不触碰音轨处理状态
    - 按处理器归入并发域：`whisper` 走本地 GPU 信号量（与整轨本地任务互斥），`gemini` 走网络 API 信号量，两域互不抢占

## 任务状态一览

| 状态 | 含义 | 终态 |
|------|------|------|
| `queued` | 已入队等待执行 | |
| `running` | 执行中 | |
| `completed` | 成功（片段任务 = 候选已接受） | ✅ |
| `no_speech` | 无可用语音段 | ✅ |
| `failed` | 失败（重试耗尽 / 异常） | ✅ |
| `cancelled` | 用户取消 | ✅ |
| `interrupted` | 被中断，重启后整轨任务恢复重跑 | ✅ |
| `awaiting_review` | 候选就绪待评审 | ✅ |
| `discarded` | 候选被放弃 | ✅ |

## 持久化

- 任务写入 Library 的 SQLite（`tasks` 表），**终态永久留存**，重启不再删除
- 旧库自动补列迁移（`kind/payload/result/时间戳`），不影响既有数据
- 片段候选结果存在任务 `result` 里，重启后仍可打开评审
- 重启时仅恢复 `queued/running/interrupted`；`awaiting_review` 原样保留，不会重跑

## 选择历史

每次任务**成功入队**后，记录该次选择的下拉项（ASR Provider、场景、Whisper 模型、翻译/ASR/合并 Profile、片段处理器等）到 `selection_history` 表。

- 下拉选项按 **最近使用 → 使用次数** 排序
- 未出现在历史中的选项保持原有确定性顺序，**不隐藏任何可用项**
- 已失效的 Profile ID 会被忽略

## 行内上下文展示

每条字幕任务行展示一组上下文信息（chips）：

- **片段时间范围**（仅片段任务）：如 `0.50 → 7.50 秒`；入队时归一化持久化，旧 payload 回退按字幕序号从字幕文档反解
- **ASR 模型**：整轨任务显示本地 Whisper 模型名 / Deepgram / ASR Profile「名称 · 模型」；片段任务显示 Whisper 模型名或音频模型 Profile
- **翻译模型**：翻译 Profile「名称 · 模型」；配置已删除时显示「翻译配置已删除」；`bilingual_once` 模式显示「音频模型一次生成双语」
- **入队 / 开始时间**：本地时区「月-日 时:分」；`started_at` 在每次实际开始执行时写入，手动重试时重置
- **Worker 摘要**（字幕 Tab 标题区）：`本地 ASR 运行/容量 · 网络 ASR 运行/容量 · 排队 N`

## 并发域（本地 vs 网络 ASR）

本地 ASR（GPU/内存瓶颈）与网络 ASR（API 配额瓶颈）分属两个独立信号量：

- **本地域**：整轨 `asr_provider=local` + 片段 `processor=whisper`；容量 = 设置页「同时加载 ASR 模型数」（`asr_concurrency`，默认 1）
- **网络域**：整轨 `asr_provider=deepgram/model` + 片段 `processor=gemini`；容量 = 设置页「网络 ASR 并发数」（`remote_asr_concurrency`，默认 2）
- 两域互不抢占：本地任务占满时网络任务照常运行，反之亦然；片段任务不再绕过信号量（此前多个本地 Whisper 片段可并发加载 large-v3 争抢显存）

## 删除

- 终态任务（`completed` / `no_speech` / `failed` / `cancelled` / `discarded`）可从任务中心删除，仅移除任务行，不碰媒体与字幕
- `awaiting_review` 不可删除（候选需先接受/放弃）；非终态任务须先取消
- 整轨任务取消后仍走「继续处理」入口，不提供重试

## 取消与重试

- 取消：整轨任务会终止子进程并标记 `cancelled`，Track 回到 `waiting`；片段任务中断在途生成，取消后可重试重新生成
- 重试：整轨任务复用同一行从断点继续（仅 failed）；片段任务复用同一行 + 原 payload 重新入队（failed / cancelled 均可，校验引用的配置仍在）
