# 安装与配置

## 前置要求

- Python >= 3.11
- [uv](https://docs.astral.sh/uv/)
- [ffmpeg](https://ffmpeg.org/)（`--asmr` 音频预处理与片段截取需要）

## 安装

=== "从源码运行"

    ```bash
    git clone https://github.com/LosLiSang/subforge.git
    cd subforge
    uv sync
    uv run subforge --help
    ```

=== "安装为全局命令"

    ```bash
    uv tool install git+https://github.com/LosLiSang/subforge.git
    subforge --help
    ```

## API Key

首次运行会生成 `~/.subforge/config.toml`。API Key 既可以写入配置，也可以通过环境变量提供：

```bash
# LLM 翻译
export LLM_API_KEY=sk-your-key
export LLM_BASE_URL=https://api.deepseek.com/v1
export LLM_MODEL=deepseek-chat

# 可选：Deepgram 云端 ASR
export DEEPGRAM_API_KEY=dg-your-key
```

!!! warning "Deepgram 费用与隐私"

    Deepgram 会把音频上传到云端，并产生 API 费用。涉及隐私或大文件批量处理前，请先确认账号额度与数据策略。

## 常用配置

```toml
[asr]
provider = "local"              # local / deepgram / model
model = "large-v3"
device = "auto"
compute_type = "float16"

[translate]
target_lang = "zh"
batch_size = 20
workers = 8

[llm]
api_key = ""
base_url = "https://api.deepseek.com/v1"
model = "deepseek-chat"

[deepgram]
api_key = ""
model = "nova-3"
keyterms = ["気付け", "布団", "性癖"]

[processing]
concurrency = 2                 # 必须 >= 1
output_dir = ""                # 空值表示输出到源文件目录
```

!!! note "Key 零落盘"

    UI 里的模型 Profile / Deepgram Key 存储在本地配置与 Library 数据库中，不会写进任务请求文件；传给子进程 Worker 时只走环境变量。

## 文档站（Material for MkDocs）

本手册使用 Material for MkDocs 构建，依赖在 `docs` 依赖组中：

```bash
uv sync --group docs          # 安装文档依赖
uv run mkdocs serve           # 本地预览 http://127.0.0.1:8000
uv run mkdocs build --strict  # 构建到 site/（已 gitignore）
```

### 在线站点（GitHub Pages）

推送到 `main` 且改动涉及 `docs/**`、`mkdocs.yml` 等时会自动构建部署
（`.github/workflows/docs.yml`，GitHub Pages 部署源需选 **GitHub Actions**）。
站点地址：<https://loslisang.github.io/subforge/>
