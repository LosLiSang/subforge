# Resume Processing — Tasks

- [x] **T1. 建立断点状态测试骨架与基础模型** ← R1.1, R1.2, R1.4, R7.1, R7.3
  - 产出：新增 `subforge/resume.py`，定义 `ResumeStateError`、`ResumeState`、`ResumeStore` 的最小结构。
  - 产出：新增 `tests/test_resume.py`，覆盖 `ResumeStore` 初始化、`jobs_dir` 创建、同一文件生成稳定 `job_key`、不同文件或语言生成不同 `job_key`。
  - 验收：`uv run pytest tests/test_resume.py -q` 通过。

- [x] **T2. 配置层与 CLI 强制重跑开关** ← R4.1, R4.2, R6.3
  - 产出：修改 `subforge/config.py`，`Config` 新增 `force: bool = False` 与 `jobs_dir: Path = DEFAULT_CONFIG_DIR / "jobs"`。
  - 产出：修改 `subforge/cli.py`，新增 `--force` 选项，并通过 `cli_overrides["force"]` 传入配置。
  - 产出：扩展 `tests/test_config.py` 或新增 CLI 测试，验证默认 `force=False`、CLI 覆盖为 `True`。
  - 验收：`uv run pytest tests/test_config.py -q` 通过。

- [x] **T3. 实现断点状态读写、校验与原子保存** ← R1.1–R1.5, R4.3, R6.4
  - 产出：完善 `subforge/resume.py`：
    - `build_job_key(job, config)`
    - `create(job, config, source_srt, target_srt)`
    - `load(job, config)`
    - `save(state)`
    - 状态 JSON schema 版本、媒体指纹、关键配置指纹校验
    - 临时文件写入后 `Path.replace()` 原子替换
  - 产出：`tests/test_resume.py` 覆盖缺失状态返回 `None`、损坏 JSON 被忽略、不匹配配置被忽略、匹配状态可加载、保存内容不包含 API Key。
  - 验收：`uv run pytest tests/test_resume.py -q` 通过。

- [x] **T4. 源/目标 SRT 可复用性校验工具** ← R2.1–R2.3, R3.1, R3.2
  - 产出：在 `subforge/resume.py` 或 `subforge/translate/srt_io.py` 中新增内部校验函数，判断 SRT 可读、非空、时间轴有效。
  - 产出：测试覆盖有效 SRT、空文件、格式错误、时间戳倒退或重叠的处理。
  - 验收：`uv run pytest tests/test_resume.py tests/test_srt_io.py -q` 通过。

- [x] **T5. 编排器接入完整目标 SRT 与源 SRT 恢复** ← R2.1–R2.4, R3.1–R3.3, R4.1–R4.3, R6.1, R6.3
  - 产出：修改 `subforge/orchestrator.py`：
    - 每个 `process_one()` 创建或加载 `ResumeStore` 状态
    - 非 `--force` 时优先校验目标 SRT，有效则跳过整个文件并标记 DONE
    - 非 `--force` 时校验源 SRT 或断点 ASR 完成状态，有效则跳过 ASR
    - `--force` 时忽略已有 SRT 和断点并记录日志
    - ASR 成功写源 SRT 后调用 `mark_asr_done()`
  - 产出：扩展 `tests/test_orchestrator.py`，mock ASR/LLM 验证目标 SRT 跳过、源 SRT 跳过 ASR、`--force` 仍重新 ASR。
  - 验收：`uv run pytest tests/test_orchestrator.py tests/test_resume.py -q` 通过。

- [x] **T6. 断点状态保存 ASR 与翻译阶段标记** ← R2.4, R5.2, R5.6, R5.7
  - 产出：完善 `ResumeStore`：
    - `mark_asr_done(state)`
    - `save_batch(state, batch_index, entries, total_batches)`
    - `mark_translation_done(state)`
    - 批次失败时保留既有 completed batches，不清空状态
  - 产出：测试覆盖 ASR done 标记、单批次保存、多批次累积保存、translation done 标记、失败后已保存批次仍存在。
  - 验收：`uv run pytest tests/test_resume.py -q` 通过。

- [x] **T7. 翻译调度接入批次级恢复** ← R5.1–R5.7, R6.2
  - 产出：修改 `subforge/translate/context.py`：
    - `translate_all()` 新增 `resume_state` 与 `resume_store` 可选参数
    - 从 `completed_batches` 预填已完成翻译
    - 只将缺失批次提交给 LLM
    - 每个新批次解析成功后调用 `save_batch()`
    - 完成后按原始 `entry.index` 输出完整结果
  - 产出：扩展 `tests/test_context.py`，验证已完成批次不调用 LLM、缺失批次会调用 LLM、缓存与新结果合并顺序正确、全部批次已完成时不调用 LLM。
  - 验收：`uv run pytest tests/test_context.py tests/test_resume.py -q` 通过。

- [x] **T8. 编排器写入翻译完成状态与恢复日志** ← R5.7, R6.1–R6.4, R7.2
  - 产出：修改 `subforge/orchestrator.py`：
    - 调用 `translate_all(..., resume_state=state, resume_store=store)`
    - 目标 SRT 写出成功后调用 `mark_translation_done()`
    - 对跳过文件、跳过 ASR、跳过批次、强制重跑、断点不可用记录日志
    - 保持单文件失败不影响其它文件
  - 产出：测试覆盖 LLM 中途失败后保留已成功批次、再次运行只处理剩余批次、批量处理某文件恢复失败不影响其它文件。
  - 验收：`uv run pytest tests/test_orchestrator.py tests/test_context.py tests/test_resume.py -q` 通过。

- [x] **T9. 文档与帮助信息更新** ← R3.3, R4.1, R6.1–R6.4
  - 产出：更新 `README.md` CLI 速查和使用示例，说明默认断点续跑、完整目标 SRT 跳过、源 SRT 跳过 ASR、`--force` 从头开始。
  - 产出：确认 `subforge --help` 包含 `--force`。
  - 验收：`uv run subforge --help` 显示 `--force`；README 示例与实际 CLI 一致。

- [x] **T10. 全量回归与版本同步** ← 全部
  - 产出：运行全量测试并修复回归。
  - 产出：如决定发布新版本，更新 `pyproject.toml` 与 `subforge/__init__.py` 版本号。
  - 验收：`uv run pytest tests/ -q` 全部通过。
