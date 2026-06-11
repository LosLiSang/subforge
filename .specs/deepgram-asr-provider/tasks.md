# Deepgram ASR Provider — Tasks

- [x] **T1. 配置层扩展 Deepgram 字段** ← R1.1, R2.1–R2.4, R3.1–R3.5
  - 产出：修改 `subforge/config.py`：
    - `Config` 新增 `asr_provider: str = "local"`
    - `Config` 新增 `deepgram_api_key: str = ""`
    - `Config` 新增 `deepgram_model: str = "nova-3"`
    - `Config` 新增 `deepgram_keyterms: list[str]`
    - `DEFAULT_CONFIG_TOML` 增加 `[asr].provider` 和 `[deepgram]` 段
    - `_apply_env_overrides()` 增加 `DEEPGRAM_API_KEY`
    - `load_config()` 解析 TOML、env 和 CLI override
  - 产出：扩展 `tests/test_config.py`，覆盖默认值、TOML 值、环境变量覆盖、CLI 覆盖。
  - 验收：`uv run pytest tests/test_config.py -q` 通过。

- [x] **T2. CLI 暴露 ASR provider 与 Deepgram 覆盖项** ← R1.2–R1.4, R2.1, R3.2
  - 产出：修改 `subforge/cli.py`：
    - 新增 `--asr-provider local|deepgram`
    - 新增 `--deepgram-api-key`
    - 新增 `--deepgram-model`
    - 将非空参数写入 `cli_overrides`
  - 产出：扩展 CLI/e2e 测试，验证 help 包含新选项，无效 provider 被拒绝，CLI override 能传入配置。
  - 验收：`uv run pytest tests/test_e2e.py tests/test_config.py -q` 通过。

- [x] **T3. Deepgram ASR 客户端骨架与错误类型** ← R2.1, R2.2, R2.5, R6.1–R6.4
  - 产出：新增 `subforge/asr/deepgram.py`：
    - `DeepgramError`
    - `DeepgramAuthError`
    - `_mask_key()`
    - `_build_query_params(model, language, keyterms)`
    - `_content_type_for_path(path)`
  - 产出：新增 `tests/test_deepgram_asr.py`，覆盖 key 掩码、query 参数、keyterm 重复参数、content-type 推断。
  - 验收：`uv run pytest tests/test_deepgram_asr.py -q` 通过。

- [x] **T4. Deepgram 响应解析为 SubtitleEntry** ← R4.1, R4.5
  - 产出：在 `subforge/asr/deepgram.py` 中实现：
    - `_entries_from_words(words)`
    - `_entry_from_transcript(transcript, duration)`
    - `_parse_response(data)`
    - 按停顿、最大时长和标点聚合 words
  - 产出：`tests/test_deepgram_asr.py` 覆盖 words 正常聚合、无 words 时 transcript 回退、空 transcript 抛错、entry index 连续、时间戳递增。
  - 验收：`uv run pytest tests/test_deepgram_asr.py -q` 通过。

- [x] **T5. Deepgram HTTP 调用与重试** ← R2.1, R2.2, R6.1–R6.4
  - 产出：实现 `transcribe(file_path, api_key, model, language, keyterms, progress_callback)`：
    - 缺 key 抛 `DeepgramAuthError`
    - POST `https://api.deepgram.com/v1/listen`
    - 401/403 不重试，抛 `DeepgramAuthError`
    - 429/5xx/timeout 最多重试 3 次
    - 成功后调用 `_parse_response()`
    - 完成时调用 `progress_callback(1.0)`
  - 产出：测试 mock `httpx.Client.post` 或 transport，覆盖成功、缺 key、401、429 重试、5xx 重试耗尽、空结果。
  - 验收：`uv run pytest tests/test_deepgram_asr.py -q` 通过。

- [x] **T6. Orchestrator 按 provider 分派 ASR** ← R1.1, R1.2, R4.2–R4.4, R6.3
  - 产出：修改 `subforge/orchestrator.py`：
    - 新增 `_run_asr(job, config, progress_callback)`
    - `local` 路径保留 `ensure_model()` 和 faster-whisper 现有参数
    - `deepgram` 路径调用 `subforge.asr.deepgram.transcribe()`
    - Deepgram 路径不调用 `ensure_model()`
    - 无效 provider 抛可理解错误
  - 产出：扩展 `tests/test_orchestrator.py`，验证默认 local、deepgram provider 调用 Deepgram、Deepgram 缺 key 文件失败、已有源 SRT 时不调用 Deepgram、`--force` 时调用 Deepgram。
  - 验收：`uv run pytest tests/test_orchestrator.py tests/test_deepgram_asr.py -q` 通过。

- [x] **T7. 断点 fingerprint 纳入 ASR provider 与 Deepgram 配置** ← R5.1–R5.4
  - 产出：修改 `subforge/resume.py`：
    - `_config_fingerprint()` 增加 `asr_provider`
    - 增加 `deepgram_model`
    - 增加 `deepgram_keyterms`
    - 不加入 `deepgram_api_key`
  - 产出：扩展 `tests/test_resume.py`，验证 local/deepgram 状态不互用、Deepgram 模型变更失效、keyterm 变更失效、API key 变更不影响匹配且不写入状态。
  - 验收：`uv run pytest tests/test_resume.py -q` 通过。

- [x] **T8. README 与配置示例更新** ← R1.4, R2.1–R2.4, R3.1–R3.5, 非功能成本控制
  - 产出：更新 `README.md`：
    - CLI 速查新增 Deepgram 参数
    - 配置文件示例新增 `[deepgram]`
    - 增加 Deepgram 使用示例
    - 提醒云端 ASR 会上传音频并产生 API 费用
    - 简述 keyterm 用法
  - 验收：`uv run subforge --help` 显示新参数；README 示例与实际 CLI 一致。

- [x] **T9. 集成回归与可选真实 Deepgram 冒烟测试** ← 全部
  - 产出：运行全量测试。
  - 产出：如果环境存在 `DEEPGRAM_API_KEY`，用短样本跑一次 `--asr-provider deepgram --force` 冒烟测试；否则记录未执行原因。
  - 产出：如决定发布新版本，更新 `pyproject.toml` 与 `subforge/__init__.py`。
  - 验收：`uv run pytest tests/ -q` 全部通过；`uv run subforge --version` 显示同步版本。
