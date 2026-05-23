# Tasks — Colored Console Logging

> 每个任务列出涉及文件与对应需求条款；任务粒度刻意保持小且独立，便于逐项验证。

## 1. 在 `subforge/config.py` 中新增 `_ColorFormatter`

- **文件**：`subforge/config.py`
- **位置**：紧跟现有 `_DEBUGFilter` 类之后（约 217 行后）
- **内容**：
    - 类继承 `logging.Formatter`
    - 类常量 `_RESET = "\x1b[0m"`
    - 类常量 `_COLORS: dict[int, str]`，键为 5 个标准 levelno，值为 ANSI 前缀：
        - `DEBUG  → "\x1b[37m"`（白）
        - `INFO   → "\x1b[34m"`（蓝）
        - `WARNING→ "\x1b[33m"`（黄）
        - `ERROR  → "\x1b[31m"`（红）
        - `CRITICAL→ "\x1b[1;31m"`（红加粗）
    - 重写 `format(self, record)`：先调用 `super().format(record)` 得到纯文本；
      若 `record.levelno` 在 `_COLORS` 中，返回 `f"{color}{text}{_RESET}"`；否则原样返回。
- **不要**修改既有 `_DEBUGFilter` 或文件其它部分。
- **覆盖需求**：R1.1–R1.5、R3.2、R3.3

## 2. 在 `setup_logging` 中给 StreamHandler 换 formatter

- **文件**：`subforge/config.py`，`setup_logging` 函数体内
- **改动**：
    - 在创建 `fmt = logging.Formatter(...)` 之后，紧接着创建
      `color_fmt = _ColorFormatter("%(asctime)s  %(levelname)-7s [%(name)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")`，
      格式串与 `fmt` 完全相同。
    - 把 `stream_handler.setFormatter(fmt)` 改成 `stream_handler.setFormatter(color_fmt)`。
    - **FileHandler 那一段一行不动**（仍 `file_handler.setFormatter(fmt)`）。
- **覆盖需求**：R1.6、R2.1、R2.2、R4.1

## 3. 追加单元测试：`_ColorFormatter` 颜色前后缀

- **文件**：`tests/test_v02_optimize.py`，`TestSetupLogging` 类内末尾追加
- **导入**：在文件顶部导入处补 `_ColorFormatter`：
  `from subforge.config import Config, setup_logging, _DEBUGFilter, _ColorFormatter`
- **测试名**：`test_color_formatter_wraps_each_level`
- **逻辑**（无需 fixture）：
    - 构造 `f = _ColorFormatter("%(message)s")`
    - 对 5 个级别（DEBUG/INFO/WARNING/ERROR/CRITICAL）各构造一个
      `logging.LogRecord("t", level, "", 0, "msg", (), None)`
    - 断言 `f.format(record)` 以对应 ANSI 前缀开头、以 `"\x1b[0m"` 结尾、且包含 `"msg"`
- **覆盖需求**：R1.1–R1.5

## 4. 追加单元测试：文件输出不含 ANSI

- **文件**：`tests/test_v02_optimize.py`，`TestSetupLogging` 类内
- **测试名**：`test_file_output_has_no_ansi`
- **逻辑**：
    - 用 `tmp_path` 构造 `Config(log_file=str(tmp_path/"test.log"), log_level="DEBUG")`
    - `setup_logging(config)`
    - 通过 `logging.getLogger("color_test")` 各发一条 INFO/ERROR/CRITICAL
    - 找到 root logger 上的 `FileHandler` 并 `flush()`/`close()`，从 root.handlers 移除以避免影响后续测试
    - 读取文件文本，断言 `"\x1b[" not in content`，且包含 `"INFO"`、`"ERROR"`、`"CRITICAL"` 三个 levelname
- **覆盖需求**：R2.1、R2.2

## 5. 追加单元测试：handlers 装配正确

- **文件**：`tests/test_v02_optimize.py`，`TestSetupLogging` 类内
- **测试名**：`test_stream_uses_color_formatter_file_does_not`
- **逻辑**：
    - `setup_logging(Config(log_file=str(tmp_path/"x.log")))`
    - 遍历 `logging.getLogger().handlers`：
        - 用 `type(h) is logging.StreamHandler` 精确匹配（排除 `FileHandler`）找出 stream，断言 `isinstance(h.formatter, _ColorFormatter)`
        - 找到 `FileHandler`（`isinstance(h, logging.FileHandler)`），断言 `not isinstance(h.formatter, _ColorFormatter)`
- **覆盖需求**：R1.6、R4.1

## 6. 运行测试套件回归

- **命令**：`pytest tests/test_v02_optimize.py -v`
- **预期**：原有 4 个 `TestSetupLogging` 用例 + 新增 3 个用例全部通过；其它分组用例不受影响。
- **覆盖需求**：R4.2

## 任务-需求矩阵

| Task | R1.1 | R1.2 | R1.3 | R1.4 | R1.5 | R1.6 | R2.1 | R2.2 | R3.1 | R3.2 | R3.3 | R4.1 | R4.2 |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| 1    |  ✓   |  ✓   |  ✓   |  ✓   |  ✓   |      |      |      |      |  ✓   |  ✓   |      |      |
| 2    |      |      |      |      |      |  ✓   |  ✓   |  ✓   |      |      |      |  ✓   |      |
| 3    |  ✓   |  ✓   |  ✓   |  ✓   |  ✓   |      |      |      |      |      |      |      |      |
| 4    |      |      |      |      |      |      |  ✓   |  ✓   |      |      |      |      |      |
| 5    |      |      |      |      |      |  ✓   |      |      |      |      |      |  ✓   |      |
| 6    |      |      |      |      |      |      |      |      |      |      |      |      |  ✓   |

> R3.1（无新增 CLI/env/Config 字段）由"任务清单中没有任何相应改动"隐式保证。
