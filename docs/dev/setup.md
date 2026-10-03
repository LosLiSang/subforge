# 开发环境

## 后端

```bash
git clone https://github.com/LosLiSang/subforge.git
cd subforge
uv sync
uv run subforge ui           # 127.0.0.1:8765
uv run pytest tests/ -q
```

测试分两层：

- `tests/unit/`：纯逻辑表驱动单测，毫秒级，不启服务、不造假库；
- `tests/integration/`：作品库、处理流水线两条黄金旅程。新需求请在已有旅程里追加断言，不要新建 E2E 文件。

测试使用临时配置与断点目录，不会读取个人配置、调用真实 Deepgram 或污染个人断点文件。

## 前端

React 19 + TypeScript + Vite，源码在 `frontend/`：

```bash
cd frontend
npm install
npm run dev                  # Vite 开发服务器，/api 代理到 127.0.0.1:8765
npm run build                # 输出到 subforge/ui/dist/（已 gitignore，不随仓库提交）
npm run lint                 # oxlint
```

`subforge/ui/dist/` 已加入 `.gitignore`，不随仓库提交。打包时 `pyproject.toml` 通过 hatch 的 `artifacts` 把本地已构建的 `dist/**` 收进 wheel，所以 `uv tool install .` 前必须先 `npm run build`；`uv tool install git+https://…` 会在干净副本上打包，拿不到 dist。

没有 `dist/index.html` 时，后端（`_should_serve_spa`）会回退到旧版 Jinja 模板页面，不会报错——看到旧界面通常就是忘了构建前端。

## 文档站（Zensical）

本手册用 [Zensical](https://zensical.org/) 构建。它是 Material for MkDocs 团队的后继项目，直接读取仓库根目录的 `mkdocs.yml`，依赖在 `docs` 依赖组里：

```bash
uv run --only-group docs zensical serve           # 本地预览 http://localhost:8000
uv run --only-group docs zensical build --strict  # 构建到 site/（已 gitignore）
```

- `--only-group docs` 只装文档依赖、不重装项目本体，`subforge ui` 运行中也能预览；
- `serve` 暂不支持 `--strict`，提交前用 `build --strict` 检查死链和锚点；
- 标题锚点使用 `pymdownx.slugs.slugify` 保留中文（Zensical 默认会丢弃非 ASCII 字符）。

推送到 `main` 且改动涉及 `docs/**`、`mkdocs.yml` 等时，`.github/workflows/docs.yml` 会自动构建并部署到 GitHub Pages（部署源需选 **GitHub Actions**）。

### 文档分组约定

- **上手 / 使用指南**：写给普通用户，用界面上的按钮名描述操作，不出现内部状态名、表名、函数名；
- **开发者参考**（`docs/dev/`）：实现细节、状态机、存储格式、设计决策。

## CLI 配置文件

CLI 首次运行生成 `~/.subforge/config.toml`，完整示例：

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
keyterms = ["気付け", "布団"]

[processing]
concurrency = 2                 # 必须 >= 1
output_dir = ""                 # 空值表示输出到源文件目录
```

UI 中的模型 Profile / Deepgram Key 存储在本地配置中，不写入任务请求文件；传给 Worker 子进程时只走环境变量。
