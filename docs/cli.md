# 命令行批处理

不想打开界面、只想给一堆音频批量出字幕？用命令行就行：不导入作品库，直接在音频旁边生成 `.ja.srt`（日文）和 `.zh.srt`（中文）两个字幕文件。

命令行会自动沿用你在界面里保存的模型配置和代理设置，终端里会实时显示每个文件的进度。

!!! tip "什么时候用命令行？"

    - 想在别的播放器里看字幕，不需要作品库；
    - 一次处理很多文件夹；
    - 在服务器上无界面运行。

    想要封面墙、双语播放、校对这些功能，请用 `subforge ui` 打开工作台。

## 命令概览

| 命令 | 作用 | 说明 |
|--------|------|----------|
| `subforge 文件或文件夹` | 批量识别并翻译，生成双语字幕 | 最常用 |
| `subforge ui` | 打开图形界面工作台 | 启动界面 |
| `subforge models` | 查看、预先下载本地 Whisper 模型 | 模型管理 |
| `subforge profiles` | 列出界面里保存的模型配置（名称可填给 `--profile`），测试连接 | 模型配置 |
| `subforge jobs` | 查看、清理未完成任务的进度记录 | 断点续跑 |
| `subforge check` | 检查 Python、ffmpeg、显卡、目录权限和模型连通性 | 排查问题 |


---

## 批量出字幕

```bash
# 普通日语音频 → 中日双语字幕
subforge audio.mp3

# ASMR / 耳语作品（放大小音量、尽量不漏耳语）
subforge audio.m4a --asmr

# 使用界面里保存的模型配置（例如名为 DeepSeek 的配置）
subforge audio.m4a --profile DeepSeek

# 仅重新翻译：保留耗时识别出的 ja.srt，只重新生成中文翻译
subforge audio.m4a --mode retranslate --profile DeepSeek

# 试运行：只列出每个文件会怎么处理，不真正调用模型、不花钱
subforge ./RJ01499022/ --dry-run

# 用在线音频模型（如 Gemini）识别
subforge audio.m4a --asr-profile GeminiAudio

# GPU 加速与多文件并发
subforge audio.m4a --asmr --device auto --compute-type float16

# 批量处理一个 RJ 作品目录
subforge ./RJ01499022/ --asmr --device auto --concurrency 2

# 忽略已有字幕与断点状态，强制从 ASR 阶段从头重新处理
subforge audio.m4a --force
```

### 处理模式（`--mode`）

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| `continue`（默认） | 已经有中文字幕的跳过；有日文字幕的只翻译；翻译到一半的接着翻 | 日常使用 |
| `retranslate` | 保留已有的日文字幕，只重新翻译中文 | 换了翻译模型或提示词 |
| `force` | 全部从头来，包括重新识别 | 识别结果很差 |

---

## 沿用界面里的设置

命令行会自动沿用你在界面里设置好的：

1. **网络代理**；
2. **全局翻译提示词**和并发数；
3. **模型配置**：用 `--profile 配置名` 直接调用；
4. **本地模型文件夹**：如果在设置里指定过离线 Whisper 模型目录，命令行也会用它。

高级用户也可以直接编辑配置文件，见[开发环境](dev/setup.md#cli-配置文件)。

---

## 其他命令

```bash
# 启动 Web UI 工作台
subforge ui
subforge ui --port 9000 --no-browser

# 检查环境（Python、ffmpeg、显卡、模型、连通性）
subforge check

# 查看 / 预先下载本地 Whisper 模型
subforge models list
subforge models download large-v3
subforge models check large-v3

# 列出模型配置、测试连接
subforge profiles list
subforge profiles test DeepSeek

# 查看 / 清理未完成任务的进度记录
subforge jobs list
subforge jobs clear --all -y
```
