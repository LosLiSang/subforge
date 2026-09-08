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

=== "片段重处理（segment_reprocess）"

    ```text
    queued → running → awaiting_review --接受--> completed
                              ↘ 放弃--> discarded
    ```

    - 提交立即返回，不阻塞页面
    - 完成后转 `awaiting_review`，行内出现「查看候选 / 放弃候选」
    - 确认时才调用范围替换改动字幕；放弃只改任务状态

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

## 取消与重试

- 取消：整轨任务会终止子进程并标记 `cancelled`，Track 回到 `waiting`；片段任务中断在途生成
- 重试：整轨任务复用同一行从断点继续；片段任务重新入队即可
