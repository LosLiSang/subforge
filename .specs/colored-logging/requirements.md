# Requirements — Colored Console Logging

## Introduction

Subforge 当前的日志通过 `subforge/config.py::setup_logging` 初始化，控制台
输出（StreamHandler→`sys.stderr`）与文件输出（FileHandler→`config.log_file`）
共用同一 `Formatter`，所有级别的日志在终端中颜色一致，难以快速区分严重程度。
本特性为**控制台输出**按级别上色，文件输出保持纯文本不变；不引入开关。

## Requirements

### Requirement 1 — 控制台日志按级别着色

**User Story:** 作为开发者，我希望在终端中看到的日志按级别有不同颜色，以便
快速识别警告与错误。

#### Acceptance Criteria

1. WHEN 一条 `DEBUG` 级别日志被写到控制台 THEN 该行整体 SHALL 以白色 ANSI
   颜色（`\x1b[37m` … `\x1b[0m`）渲染。
2. WHEN 一条 `INFO` 级别日志被写到控制台 THEN 该行整体 SHALL 以蓝色 ANSI
   颜色（`\x1b[34m` … `\x1b[0m`）渲染。
3. WHEN 一条 `WARNING` 级别日志被写到控制台 THEN 该行整体 SHALL 以黄色 ANSI
   颜色（`\x1b[33m` … `\x1b[0m`）渲染。
4. WHEN 一条 `ERROR` 级别日志被写到控制台 THEN 该行整体 SHALL 以红色 ANSI
   颜色（`\x1b[31m` … `\x1b[0m`）渲染。
5. WHEN 一条 `CRITICAL` 级别日志被写到控制台 THEN 该行整体 SHALL 以红色加粗
   ANSI 颜色（`\x1b[1;31m` … `\x1b[0m`）渲染。
6. 着色 SHALL 仅作用于 `setup_logging` 安装到根 logger 的 StreamHandler；
   不得修改任何其它 handler 的输出。

### Requirement 2 — 文件日志保持纯文本

**User Story:** 作为运维/排错者，我希望日志文件可以直接 `cat`/`grep`，不被
转义码污染。

#### Acceptance Criteria

1. WHEN 任意级别日志写入 `config.log_file` THEN 文件内容 SHALL NOT 包含 ANSI
   转义序列（即不含字节序列 `\x1b[`）。
2. 文件输出格式 SHALL 与现状逐字一致：
   `"%(asctime)s  %(levelname)-7s [%(name)s] %(message)s"`，日期 `%Y-%m-%d %H:%M:%S`。

### Requirement 3 — 无开关、无新依赖

**User Story:** 作为维护者，我不希望为这个小特性引入新配置项或第三方包。

#### Acceptance Criteria

1. 实现 SHALL NOT 新增 CLI 参数、环境变量或 `Config` 字段。
2. 实现 SHALL NOT 引入新的 Python 依赖（不使用 `colorama`、`rich` 等），
   仅使用标准库 + 直接写 ANSI 转义码。
3. 控制台格式（除颜色外）SHALL 与当前文件格式保持一致，便于肉眼对照。

### Requirement 4 — 不破坏现有降级路径与测试

**User Story:** 作为维护者，我需要保证现有的"FileHandler 创建失败 → 降级为
仅 stderr"路径与既有测试不被破坏。

#### Acceptance Criteria

1. WHEN `FileHandler` 因 `OSError` 创建失败 THEN `setup_logging` SHALL 仍然
   只保留带颜色的 StreamHandler，并通过 `root.warning(...)` 给出降级提示。
2. `tests/test_v02_optimize.py` 现有断言 SHALL 全部继续通过，无需修改。
