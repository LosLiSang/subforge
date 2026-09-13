# CLI 离线批处理

SubForge CLI 是专注「离线批处理」的命令行工具：免入库、不碰 SQLite 数据库，直接面向任意本地音频文件或目录，在原地生成 `.ja.srt` 与 `.zh.srt` 双语字幕。

CLI 采用 Rich 富文本呈现多任务 Live 进度卡片与执行报告，并全面打通复用 Web 端配置的模型 Profile 与代理设置。

## 命令概览

| 命令组 | 作用 | 对应功能 |
|--------|------|----------|
| `subforge [INPUTS...]` / `process` | 直接音频/目录批量识别与翻译（支持 ASMR 预设、Profile 复用、重译模式、dry-run 预检） | 核心离线批处理管线 |
| `subforge ui` | 启动本地 Library UI Web 工作台服务 | Web 界面启动 |
| `subforge models` | Faster-Whisper 本地模型离线缓存查看、预下载与直接目录检查 | 模型缓存管理 |
| `subforge profiles` | 查看可用的统一模型 Profile 列表（供 `--profile` 填入）与网络连通性测试 | 模型配置 |
| `subforge jobs` | CLI 离线批处理断点状态查看与清理 | 断点缓存目录 |
| `subforge check` (`doctor`) | Python、FFmpeg、CUDA/GPU、目录权限与 API 连通性综合体检 | 排障与环境诊断 |

> **职责边界说明**：作品库归档（封面墙、播放器、声优/社团关联、片段重做审核）由 Web UI 管理；CLI 专注于高效、原地的离线文件批量处理。

---

## 1. 批量识别与翻译 (`subforge [INPUTS...]`)

```bash
# 普通日语音频 → 中日双语字幕
subforge audio.mp3

# ASMR / 耳语作品（低阈值 VAD、响度预处理、抑制幻觉）
subforge audio.m4a --asmr

# 直接复用 Web 端已配置的模型 Profile（例如已保存的 DeepSeek）
subforge audio.m4a --profile DeepSeek

# 仅重新翻译：保留耗时识别出的 ja.srt，只重新生成中文翻译
subforge audio.m4a --mode retranslate --profile DeepSeek

# 试运行：预检目录并输出计划（全处理 / 仅翻译 / 断点续跑 / 跳过），不消耗 token
subforge ./RJ01499022/ --dry-run

# 原生音频模型 ASR（如调用已配置的 Gemini 或音频模型分片识别）
subforge audio.m4a --asr-profile GeminiAudio

# GPU 加速与多文件并发
subforge audio.m4a --asmr --device auto --compute-type float16

# 批量处理一个 RJ 作品目录
subforge ./RJ01499022/ --asmr --device auto --concurrency 2

# 忽略已有字幕与断点状态，强制从 ASR 阶段从头重新处理
subforge audio.m4a --force
```

### 处理模式 (`--mode`)

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| `continue` (默认) | 目标字幕完整则跳过；源字幕完整则跳过 ASR；翻译中断则续跑剩余批次 | 日常断点续跑 |
| `retranslate` (`--retranslate-only`) | **保留已有 `ja.srt`**，清空历史翻译状态并从头重新翻译 `zh.srt` | 换了更好模型或微调了提示词，无需重新跑 ASR |
| `force` (`--force`) | 忽略所有已有字幕与断点，强制从 ASR 阶段从头重做 | 音频重新识别 |

---

## 2. 配置与设置继承

CLI 离线批处理会自动继承用户全局配置目录 `~/.subforge/` 中的内容：

1. **继承 Web 代理设置**：自动读取 `ui.json` 中的 `proxy_url`（如 `http://127.0.0.1:7890`），用于拉取模型与 API 访问。
2. **继承默认翻译 Prompt 与 Worker 数**：自动使用 Web 端设置的并发参数与提示词。
3. **复用模型 Profiles**：通过 `--profile <name>` 直接调用 `model-profiles.json` 中配置的任何模型。
4. **直接目录模式**：若在 Web 设置页为 `medium` 或 `large-v3` 指定了离线 CTranslate2 目录，CLI 同样自动走离线目录。

---

## 3. 辅助子命令

```bash
# 启动 Web UI 工作台
subforge ui
subforge ui --port 9000 --no-browser

# 系统与环境健康诊断（Python、FFmpeg、CUDA、模型缓存、LLM 连通性）
subforge check

# 查看/预下载本地 faster-whisper 模型
subforge models list
subforge models download large-v3
subforge models check large-v3

# 查看可用的模型 Profile 列表与测试连接
subforge profiles list
subforge profiles test DeepSeek

# 查看/清理批处理断点记录
subforge jobs list
subforge jobs clear --all -y
```
