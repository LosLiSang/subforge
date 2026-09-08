# 常见问题与排障

## ASR / 识别

??? question "耳语被整段吞掉，字幕大片缺失？"

    用 ASMR 预设（`--asmr` / 场景选 ASMR）。双耳录音会自动拆声道分别转写；若仍缺失，尝试调低 VAD 阈值（0.2）并确认开了 ffmpeg 响度归一化。

??? question "结尾多了「ご視聴ありがとうございました」这类字幕？"

    Whisper 对结尾静音的幻觉，时间戳还可能超出媒体长度。影响：

    - 新任务：写盘前已自动钳制/丢弃，不会再落盘
    - 旧数据：编辑或片段替换时会**自动钳制修复**，不再阻塞操作

??? question "模型下载失败 / 无法访问 Hugging Face？"

    设置页填模型下载代理；或为 `medium`/`large-v3` 指定已有的 CTranslate2 模型目录（含 `model.bin` 与 `config.json`），完全离线。

## 模型配置

??? question "Gemini 当 ASR 时长音频怎么处理？"

    按 Profile 的「单次请求上限」自动分片（默认 60 秒）：语音区间打包成块逐块转写，时间轴由 SubForge 映射回绝对时间。语音检测失败退化为等长分片，不会整段一次发送。

??? question "为什么合并模型不能改时间轴？"

    实测 Gemini 直接产出时间轴会压缩/扭曲。因此合并只做文本层校对（去重/标点/术语），绝对时间轴由 SubForge 确定性生成。

??? question "旧配置迁移后去哪了？"

    `llm-profiles.json` 与 `gemini-audio-profiles.json` 首次加载自动合并为 `~/.subforge/model-profiles.json`，原文件保留不删。

## 任务

??? question "任务重启后还在吗？"

    在。终态任务永久留存于 Library 的 SQLite；`queued/running/interrupted` 的整轨任务重启后自动恢复，`awaiting_review` 的候选原样保留可继续评审。

??? question "片段重处理提交后没弹候选？"

    现在是异步任务：提交立即返回，去**任务中心 → 字幕**看进度；完成后点「查看候选」。

??? question "确认候选时报「源语言字幕结束时间超过媒体时长」？"

    已修复：历史越界条目会在操作前自动钳制。若仍遇到，说明是极旧的库数据，可对该 Track 做一次编辑/重处理触发修复。

## 翻译

??? question "翻译返回空 / 半截？"

    已内置防护：空响应最多重试 3 次并串行化；个别行缺失按 5 条/1 条递进补翻。仍失败时任务会 failed 并保留断点，重试只补未完成批次。

??? question "字幕顺序或条数对不上？"

    播放页「校正」可手动修；范围性错误建议用[片段重处理](segment-reprocess.md)重新生成候选。

## Library

??? question "Library 能换盘/迁移吗？"

    能。文件系统资产与每个 Item 的 `metadata.json` 是事实来源，SQLite 只是可重建的索引；整体拷贝目录即可迁移。

??? question "导入会动我的原文件吗？"

    不会。导入是复制 + 校验；删除只进 `.trash`。SubForge 永不移动、修改或删除来源文件。
