# SubForge v0.2 优化 — Tasks

- [x] **T1. 配置层扩展：新增字段与日志初始化** ← R2.1, R3.1, R3.3, R3.6
  - 产出：`config.py` 中 `Config` dataclass 新增 `translate_workers: int = 8`、`log_level: str = "INFO"`、`log_file: str = "subforge.log"`
  - 产出：`DEFAULT_CONFIG_TOML` 新增 `[translate] workers = 8` 和 `[logging]` 段（`level = "INFO"`, `file = "subforge.log"`）
  - 产出：`_apply_env_overrides()` 新增 `SUBFORGE_LOG_LEVEL` → `("logging", "level")` 映射
  - 产出：`load_config()` 解析 `[translate].workers`、`[logging].level`、`[logging].file`
  - 产出：`config.py` 中新增 `setup_logging(config: Config) -> None` 函数
    - root logger 设置级别为 `config.log_level`
    - StreamHandler(sys.stderr)：加 `DEBUGFilter`，非 DEBUG 模式时拒绝 DEBUG 消息
    - FileHandler(config.log_file)：接受所有级别
    - Formatter：`"%(asctime)s  %(levelname)-7s [%(name)s] %(message)s"`，日期格式 `%Y-%m-%d %H:%M:%S`
    - FileHandler 创建失败时捕获 OSError，降级为仅 stderr
  - 验收：`python -c "from subforge.config import load_config, setup_logging; c=load_config(); setup_logging(c)"` 无报错；检查 `subforge.log` 是否生成

- [x] **T2. 全局日志替换：print → logging** ← R3.2, R3.4
  - 产出：以下文件中所有 `print(..., file=sys.stderr)` 替换为对应的 `logging` 调用：
    - `orchestrator.py`：`logger.info` / `logger.exception`
    - `translate/llm_client.py`：`logger.info`（API 调用）/ `logger.warning`（重试）/ `logger.error`（失败）
    - `asr/engine.py`：`logger.info`（模型加载/转写进度）
    - `asr/model_manager.py`：`logger.info`
    - `cli.py`：`logger.error`（无文件 / 中断）
  - 每个模块使用 `logger = logging.getLogger(__name__)`
  - `llm_client._mask_key` 逻辑保留，API Key 仍掩码后输出
  - 异常处使用 `logger.exception()` 记录完整 traceback
  - 验收：运行 `subforge --help`，stderr 无 `print` 风格裸输出；检查 `subforge.log` 包含格式化日志

- [x] **T3. CLI 新增 --log-level 参数** ← R3.3
  - 产出：`cli.py` 新增 `@click.option("--log-level", ...)`，类型 `click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"])`，默认 `None`
  - 产出：`cli_overrides` 字典传递 `log_level`
  - 产出：`load_config()` 接收并应用 `log_level` CLI override
  - 产出：`setup_logging()` 在 `main()` 中于 `load_config()` 之后立即调用
  - 验收：`subforge --log-level DEBUG audio.mp3` 日志文件中出现 DEBUG 行；`--log-level WARNING` 时终端不显示 INFO 行

- [x] **T4. ASR 本地模型缓存检测** ← R4.1–R4.5
  - 产出：重写 `asr/model_manager.py` 的 `ensure_model()`
    - 函数签名：`ensure_model(model_size: str, models_dir: Path) -> tuple[bool, bool]`
    - 返回值：`(available: bool, local_files_only: bool)`
    - 使用 `huggingface_hub.try_to_load_from_cache()` 检测 `f"models--Systran--faster-whisper-{model_size}"` 是否在缓存中
    - 检测到 → `logger.info("Model %s found locally, skipping download.", model_size)`，返回 `(True, True)`
    - 未检测到 → `logger.info("Model %s not cached, will download.", model_size)`，返回 `(True, False)`
  - 产出：修改 `asr/engine.py` 的 `transcribe()`
    - 新增 `local_files_only: bool = False` 参数
    - 传给 `WhisperModel(..., local_files_only=local_files_only)`
    - 若 `local_files_only=True` 且加载失败（捕获 `Exception`）→ `logger.warning("Local model load failed, retrying with download.")` → 以 `local_files_only=False` 重试
  - 产出：修改 `orchestrator.py` 的 `process_one()`，调用 `ensure_model()` 获取 `local_files_only`，传给 `asr_transcribe()`
  - 验收：删除 `~/.subforge/models/` 中模型→运行→日志显示 "not cached, will download"；再次运行→日志显示 "found locally, skipping download" 且不发起网络请求

- [x] **T5. ASR 进度条集成** ← R1.1, R1.3, R1.4, R1.5
  - 产出：修改 `asr/engine.py` 的 `transcribe()`
    - 新增 `progress_callback: Callable[[float], None] | None = None` 参数
    - 从 `model.transcribe()` 返回的 `info` 获取 `info.duration`
    - 遍历 segments 时累计 `seg.end`，计算 `progress = min(current_end / total_duration, 1.0)`，调用 `progress_callback(progress)`
    - `total_duration` 为 0 或 None 时回退为基于 segment 数量的百分比
  - 产出：修改 `orchestrator.py` 的 `process_one()`
    - ASR 阶段开始时创建 tqdm 实例：`tqdm(total=1.0, desc=f"[ASR] {job.file_path.name}", position=job_slot, leave=False)`
    - `progress_callback` 闭包调用 `pbar.n = value; pbar.refresh()`
    - ASR 完成时 `pbar.close()`
  - 验收：运行 `subforge audio.mp3`，终端出现 `[ASR] audio.mp3: 100%|██████████| 1.00/1.00` 进度条

- [x] **T6. 翻译并发调度器（DependencyTracker）** ← R2.1–R2.4
  - 产出：重写 `translate/context.py` 的 `translate_all()`
    - 新增 `DependencyTracker` 类（私有，同文件）：
      - `__init__(self, num_batches: int, context_size: int, batch_size: int)`：构建依赖图（batch N 依赖 batch N-1，当 context_size > 0 时）
      - `is_ready(batch_index) -> bool`：检查该批次所有依赖是否已完成
      - `mark_done(batch_index)`：标记完成，返回新就绪的批次索引列表
      - `all_done() -> bool`：所有批次完成
    - `translate_all()` 新增 `progress_callback: Callable[[int, int], None] | None` 参数
    - 内部流程：
      1. `build_batches()` → 批次列表
      2. 初始化 `DependencyTracker`、就绪队列、`asyncio.Semaphore(workers)`
      3. 初始就绪批次（批 0）入队
      4. worker 协程循环：等待 semaphore → 取就绪批次 → `llm_translate_fn()` → 存储译文 → `mark_done()` → 释放 semaphore → 新就绪批次入队
      5. 所有批次完成后，按 entry.index 排序输出
    - 每次批次完成时调用 `progress_callback(done_count, total_count)`
  - 验收：context_size=0 时所有批次并发（检查日志时间戳接近）；context_size=10 时批次串行（检查依赖正确性）；batch_size=20, context_size=10 时 60 条字幕生成 3 个批次，翻译结果按原始顺序输出

- [x] **T7. 翻译进度条集成** ← R1.2, R1.3, R1.4, R1.5
  - 产出：修改 `orchestrator.py` 的 `process_one()`
    - 翻译阶段开始时创建 tqdm：`tqdm(total=total_batches, desc=f"[Translate] {job.file_path.name}", position=job_slot, leave=False)`
    - `progress_callback` 闭包：`pbar.update(1)`
    - 翻译完成时 `pbar.close()`
  - 产出：`orchestrator.py` 新增 `_allocate_slot()` / `_release_slot()` 辅助函数，管理 tqdm `position` 槽位池（0 到 concurrency-1）
  - 验收：ASR 完成后翻译阶段出现 `[Translate] audio.mp3: 100%|██████████| 3/3` 进度条

- [x] **T8. 集成验证与测试** ← 全部需求
  - 产出：创建 `tests/test_v02_optimize.py`
    - `test_setup_logging_creates_file`：调用 setup_logging 后 subforge.log 存在
    - `test_setup_logging_fallback_no_file`：模拟不可写路径，验证降级不抛异常
    - `test_model_cache_detection`：mock `try_to_load_from_cache` 返回路径 / None，验证 ensure_model 返回值
    - `test_model_local_load_fallback`：mock WhisperModel 首次抛异常，验证以 `local_files_only=False` 重试
    - `test_dependency_tracker_linear`：context_size=10, batch_size=20, 3 批次的依赖链正确（0→1→2）
    - `test_dependency_tracker_independent`：context_size=0, 所有批次无依赖
    - `test_translate_all_ordering`：验证翻译结果按 entry.index 排序
    - `test_translate_all_serial_fallback`：workers=1 时与 v0.1 行为一致
  - 验收：`pytest tests/test_v02_optimize.py -v` 全部通过

- [x] **T9. 更新 pyproject.toml 版本号**
  - 产出：`pyproject.toml` 中 `version = "0.1.0"` → `version = "0.2.0"`
  - 产出：`subforge/__init__.py` 中 `__version__` 同步更新
  - 验收：`subforge --version` 显示 `subforge, version 0.2.0`
