# Base Auto Subtitle — Tasks

## 依赖顺序

```
T1 项目脚手架
 └─ T2 数据模型
     └─ T3 配置系统
         ├─ T4 文件扫描器
         ├─ T5 SRT 读写
         │   └─ T7 时间轴微调
         ├─ T6 ASR 引擎
         │   └─ T7 使用 ASR 输出
         └─ T8 LLM 客户端
             └─ T9 上下文窗口构建器
                 └─ T10 编排器
                     └─ T11 CLI 入口
                         └─ T12 端到端集成 & 冒烟测试
```

---

- [x] **T1. 项目脚手架搭建** ← 全局
  - 产出：
    - `pyproject.toml`（UV 项目定义、依赖声明、entry point `base-auto-subtitle`）
    - `uv.lock`
    - 目录结构：`base_auto_subtitle/`、`base_auto_subtitle/asr/`、`base_auto_subtitle/translate/`
    - 各模块 `__init__.py`
    - `tests/` 目录 + `conftest.py`（pytest 配置）
  - 验收：
    - `uv sync` 成功安装所有依赖
    - `uv run pytest` 可运行（0 tests 也视为通过）

- [x] **T2. 数据模型定义** ← R2.4, R4.1
  - 产出：
    - `base_auto_subtitle/models.py`：`SubtitleEntry`、`Job`、`JobStatus` dataclass
    - `tests/test_models.py`：构造与字段默认值测试
  - 验收：
    - `uv run pytest tests/test_models.py` 全部通过

- [x] **T3. 配置系统** ← R5.1, D6
  - 产出：
    - `base_auto_subtitle/config.py`：
      - 读取 `~/.subforge/config.toml`（首次不存在则生成默认）
      - CLI 参数 > 环境变量 > config.toml > 硬编码默认值 的优先级合并
      - `Config` dataclass 汇总所有可配置项
    - `tests/test_config.py`：默认值、TOML 解析、CLI 覆盖、环境变量覆盖
  - 验收：
    - `uv run pytest tests/test_config.py` 全部通过
    - 手动：删除 `~/.subforge/config.toml` 后运行配置读取，验证自动生成默认文件

- [x] **T4. 文件扫描器** ← R1.1, R1.2
  - 产出：
    - `base_auto_subtitle/scanner.py`：
      - `scan_paths(paths: list[Path]) -> list[Path]`：展开目录递归、过滤支持格式
      - 支持格式：`.mp3 .mp4 .wav .m4a .flac`
      - 不支持的格式输出 `Skipping: xxx (unsupported format)` 到 stderr
    - `tests/test_scanner.py`：单文件、多文件、目录递归、混合格式过滤、不支持格式警告
  - 验收：
    - `uv run pytest tests/test_scanner.py` 全部通过

- [x] **T5. SRT 文件读写** ← R2.4, R3.5
  - 产出：
    - `base_auto_subtitle/translate/srt_io.py`：
      - `write_srt(entries: list[SubtitleEntry], path: Path)`：写入 SRT 格式文件
      - `read_srt(path: Path) -> list[SubtitleEntry]`：解析 SRT 文件
    - `tests/test_srt_io.py`：写入→回读一致性、时间戳格式化、特殊字符
  - 验收：
    - `uv run pytest tests/test_srt_io.py` 全部通过
    - 手动：生成的 SRT 文件用 PotPlayer 加载可正常显示

- [x] **T6. ASR 引擎封装** ← R2.1–R2.4
  - 产出：
    - `base_auto_subtitle/asr/engine.py`：
      - `transcribe(file_path: Path, model_size: str, language: str, model_dir: Path) -> list[SubtitleEntry]`
      - 封装 faster-whisper 的 `WhisperModel` 加载与 `transcribe()` 调用
      - 将 faster-whisper 输出的 segments 转为 `list[SubtitleEntry]`
    - `base_auto_subtitle/asr/model_manager.py`：
      - `ensure_model(model_size: str, models_dir: Path)`：检查模型是否存在，不存在则触发下载
    - `tests/test_asr_engine.py`：用短音频（<30s）验证转写输出结构（至少需要 GPU 或 CPU 可跑 tiny 模型）
      - 验证输出为 `list[SubtitleEntry]`
      - 验证时间戳递增且无重叠
  - 验收：
    - `uv run pytest tests/test_asr_engine.py` 全部通过

- [x] **T7. 时间轴微调** ← R2.4（可选优化）
  - 产出：
    - `base_auto_subtitle/timeline.py`：
      - `merge_short_entries(entries: list[SubtitleEntry], min_duration: float = 0.5) -> list[SubtitleEntry]`
      - 合并时长低于阈值的相邻条目（如果产生超过 max_duration 则跳过合并）
      - `adjust_gaps(entries, max_gap=0.1)`：小幅调整间隔
    - `tests/test_timeline.py`：短条目合并、边界情况（单项、全短、全长）
  - 验收：
    - `uv run pytest tests/test_timeline.py` 全部通过

- [x] **T8. LLM 客户端** ← R3.6, R3.7
  - 产出：
    - `base_auto_subtitle/translate/llm_client.py`：
      - `translate_batch(messages: list[dict], config: Config) -> str`：单次翻译调用
      - 使用 `httpx.AsyncClient`，`tenacity` 指数退避重试（1s→2s→4s，最多3次）
      - 401 错误不重试；429 优先读 `Retry-After` 头；超时按指数退避
      - 日志不记录完整 API Key（仅前4后4）
    - `tests/test_llm_client.py`：使用 httpx mock / pytest-httpx 模拟成功、超时、429、401 场景
  - 验收：
    - `uv run pytest tests/test_llm_client.py` 全部通过

- [x] **T9. 上下文窗口构建器** ← R3.1, R3.2
  - 产出：
    - `base_auto_subtitle/translate/context.py`：
      - `build_batches(entries: list[SubtitleEntry], batch_size: int, context_size: int, previous_translations: list[str] | None) -> list[list[SubtitleEntry]]`
      - 按 K=20, N=10 拆分批次，构建滑动上下文窗口
      - 构建发给 LLM 的 messages（system prompt + context + batch）
      - `translate_all(entries, llm_client, config) -> list[SubtitleEntry]`：遍历批次调用 LLM
    - `tests/test_context.py`：批次数量、边界（条目数 < K）、上下文正确拼接、前瞻条目不含译文
  - 验收：
    - `uv run pytest tests/test_context.py` 全部通过

- [x] **T10. 编排器** ← R4.1–R4.4, R6.1–R6.2
  - 产出：
    - `base_auto_subtitle/orchestrator.py`：
      - `process_all(jobs: list[Job], config: Config)`：asyncio 入口
      - `process_one(job: Job, config: Config)`：单个文件 ASR → 微调 → 翻译 的完整流水线
      - `asyncio.Semaphore` 控制并发数
      - `asyncio.Queue` 管理等待队列
      - 实时进度输出（tqdm），每文件两阶段进度（ASR / 翻译）
      - 错误捕获：ASR 失败 → 标记 FAILED，继续；翻译失败 → 标记 FAILED 但保留源语言 SRT
      - 全部完成后打印汇总：成功数、失败数、各文件耗时
    - `tests/test_orchestrator.py`：mock ASR + mock LLM，验证并发数控制、队列自动推进、失败隔离、汇总输出
  - 验收：
    - `uv run pytest tests/test_orchestrator.py` 全部通过

- [x] **T11. CLI 入口** ← R5.1–R5.3
  - 产出：
    - `base_auto_subtitle/cli.py`：`click` 命令，参数定义、帮助信息
    - `pyproject.toml` 注册 `[project.scripts]` entry point：`base-auto-subtitle`
  - 验收：
    - `uv run base-auto-subtitle --help` 显示完整帮助
    - `uv run base-auto-subtitle test.mp3` 能走通空跑（参数校验通过，进入扫描流程）

- [x] **T12. 端到端集成与冒烟测试** ← 全部
  - 产出：
    - `tests/test_e2e.py`：用一段 30s 日语测试音频，真实走通 扫描 → ASR → 微调 → 翻译 → 输出 SRT
    - 验证产物：源语言 `.srt` + 目标语言 `_zh.srt` 文件存在且内容非空
  - 验收：
    - `uv run pytest tests/test_e2e.py` 通过
    - 手动：`uv run base-auto-subtitle <测试音频> --concurrency 1` 端到端成功
    - 手动：输出 SRT 在 PotPlayer 中可正常加载显示

---

## 任务关联需求速查

| 任务 | 关联需求 |
|---|---|
| T1 | 全局脚手架 |
| T2 | R2.4, R4.1 |
| T3 | R5.1, D6 |
| T4 | R1.1, R1.2 |
| T5 | R2.4, R3.5 |
| T6 | R2.1–R2.4 |
| T7 | R2.4（可选） |
| T8 | R3.6, R3.7 |
| T9 | R3.1, R3.2 |
| T10 | R4.1–R4.4, R6.1–R6.2 |
| T11 | R5.1–R5.3 |
| T12 | 全部 |
