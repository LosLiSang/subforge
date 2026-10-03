# 安装与启动

## 需要准备什么

| 软件 | 用途 | 获取 |
|------|------|------|
| Python 3.11 或更新 | 运行 SubForge | <https://www.python.org/downloads/> |
| uv | 安装和运行 SubForge 的工具 | <https://docs.astral.sh/uv/getting-started/installation/> |
| ffmpeg | 处理音频、从视频里提取音轨 | <https://ffmpeg.org/download.html>（装好后要能在终端里运行 `ffmpeg`） |

!!! tip "要不要显卡？"

    不是必须的。用**本地 Whisper** 识别时，NVIDIA 显卡会快很多；没有显卡也能用 CPU 跑，只是慢。
    如果用 Gemini 这类**在线音频模型**或 Deepgram 识别，就完全不吃本机显卡。

## 安装

打开终端（Windows 上用 PowerShell 或 Windows Terminal），依次执行：

=== "装成全局命令（推荐）"

    ```bash
    uv tool install git+https://github.com/LosLiSang/subforge.git
    subforge ui
    ```

    以后在任何目录输入 `subforge ui` 就能启动。更新时执行 `uv tool upgrade subforge`。

=== "从源码运行"

    ```bash
    git clone https://github.com/LosLiSang/subforge.git
    cd subforge
    uv sync
    uv run subforge ui
    ```

    以后在 `subforge` 目录里执行 `uv run subforge ui` 启动。

不需要安装 Node.js，界面已经打包在里面了。

## 第一次启动

1. 运行 `subforge ui` 后，浏览器会自动打开工作台（地址是 `http://127.0.0.1:8765`）。
2. 选择一个**作品库文件夹**：以后导入的音频、封面和字幕都会存放在这里。建议选一个空间充足的盘，例如 `D:\ASMR-Library`。
3. 进入「翻译配置」页，至少添加一个**翻译模型**（例如 DeepSeek），否则只能识别日文、不能翻译。详见[模型配置](model-profiles.md)。
4. 进入「设置 → 默认模型配置」，选择默认用哪个引擎识别、用哪个模型翻译。

接下来就可以[处理第一部作品](quickstart.md)了。

!!! note "只在本机访问"

    工作台只监听本机地址 `127.0.0.1`，同一网络里的其他设备访问不到。关掉终端窗口，工作台也就停止了。

!!! note "你的 API Key 存在哪里？"

    在界面里填写的 API Key 只保存在本机的配置文件里，不会上传到任何地方。编辑配置时 Key 留空表示保持原值不变。

## 修改端口或不自动打开浏览器

```bash
subforge ui --port 9000        # 换一个端口
subforge ui --no-browser       # 不自动打开浏览器
```

## 检查环境

遇到问题时先运行一次体检，它会检查 Python、ffmpeg、显卡和模型连通性：

```bash
subforge check
```

## 进阶：配置文件与环境变量

主要给[命令行批处理](cli.md)用。首次运行会生成 `~/.subforge/config.toml`（Windows 上是 `C:\Users\你的用户名\.subforge\config.toml`）。

API Key 也可以通过环境变量提供：

```bash
export LLM_API_KEY=sk-your-key
export LLM_BASE_URL=https://api.deepseek.com/v1
export LLM_MODEL=deepseek-chat
export DEEPGRAM_API_KEY=dg-your-key   # 可选
```

常用配置项：

```toml
[asr]
provider = "local"              # local（本地 Whisper）/ deepgram / model（在线音频模型）
model = "large-v3"
device = "auto"

[llm]
api_key = ""
base_url = "https://api.deepseek.com/v1"
model = "deepseek-chat"

[processing]
concurrency = 2                 # 同时处理几个文件
output_dir = ""                 # 留空表示字幕输出到音频所在目录
```

!!! warning "Deepgram 的费用与隐私"

    Deepgram 会把音频上传到它的服务器，并按时长收费。处理私密内容前请先确认。
