# 开发者参考

这一组页面面向想了解内部实现、参与开发或排查深层问题的人。只想使用 SubForge 的话，看「上手」和「使用指南」就够了。

| 页面 | 内容 |
|------|------|
| [开发环境](setup.md) | 源码运行、测试、前端开发、文档站构建 |
| [处理管线](pipeline.md) | ASR → 时间轴修正 → 翻译的流程，ASMR 预设参数，翻译防护 |
| [模型 Profile 内部机制](model-profiles.md) | 能力标记、协议、分片与合并、旧配置迁移、选择历史 |
| [任务系统](tasks.md) | 任务状态机、持久化、重试语义、并发域 |
| [字幕存储与校验](subtitles.md) | 快照、结构编辑、候选替换、时间轴校验规则 |
| [前端界面规范](frontend-ui-spec.md) | 各页面的字段、数据来源与交互 |
| [术语表](glossary.md) | 领域用语定义（源自仓库根目录 `CONTEXT.md`） |
| [架构决策记录](adr/index.md) | 产品定位、文件系统权威等关键决策 |

## 架构速览

```text
Browser   React 19 + TS            subforge/ui/dist/
   |  REST /api/*
FastAPI   routes + TaskManager     subforge/ui/app.py, ui/tasks.py
   |  spawn
Worker    subprocess, JSONL events subforge/worker.py
   |
Pipeline  ASR -> timeline -> translate   subforge/orchestrator.py
   |
Library   subforge/library.py
          - filesystem: media / SRT / metadata.json / snapshots  (source of truth)
          - SQLite: index, tasks, selection_history              (rebuildable)
```

- **文件系统是事实来源**，SQLite 只是索引，见 [ADR-0002](adr/0002-library-filesystem-authority.md)。
- **时间轴归 SubForge**：模型只产出文本，绝对时间轴由程序确定性生成、校验和钳制。
- **UI 只监听 `127.0.0.1`**（`server.py` 强制校验 host 与 `allowed_hosts`）。
