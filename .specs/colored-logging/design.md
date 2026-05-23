# Design — Colored Console Logging

## Overview

只动一处文件 `subforge/config.py`：新增 `_ColorFormatter`（继承
`logging.Formatter`），在 `setup_logging` 中把 StreamHandler 的 formatter
从普通 `Formatter` 换成 `_ColorFormatter`。FileHandler 继续使用原有的纯文本
`Formatter`，因此磁盘日志格式逐字不变。

零新增依赖、零新增配置项、零新增 CLI 参数。

## Architecture

```
root logger
├── StreamHandler(sys.stderr)
│     └── _ColorFormatter      ← 新增：按 levelno 包 ANSI 颜色
└── FileHandler(log_file)
      └── Formatter (原样)     ← 不变
```

## Components and Interfaces

### `_ColorFormatter(logging.Formatter)`

私有类（前导下划线表示仅内部使用，类似既有的 `_DEBUGFilter`）。

```python
class _ColorFormatter(logging.Formatter):
    """Wrap each formatted line in level-specific ANSI color codes.

    Applied only to the console StreamHandler; FileHandler keeps plain text.
    """

    _RESET = "\x1b[0m"
    _COLORS = {
        logging.DEBUG:    "\x1b[37m",     # white
        logging.INFO:     "\x1b[34m",     # blue
        logging.WARNING:  "\x1b[33m",     # yellow
        logging.ERROR:    "\x1b[31m",     # red
        logging.CRITICAL: "\x1b[1;31m",   # bold red
    }

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        color = self._COLORS.get(record.levelno)
        return f"{color}{text}{self._RESET}" if color else text
```

- 继承 `logging.Formatter`，复用现有 `fmt` 字符串和 `datefmt`。
- 通过 `super().format(record)` 拿到与文件输出**完全一致**的文本，再用 ANSI
  代码包整行，保证肉眼对照方便（R3.3）。
- 未知级别（如自定义 `logging.addLevelName`）的记录回落到无色，避免抛错。

### `setup_logging(config: Config)` 改动

仅替换 StreamHandler 的 formatter；FileHandler 保持使用原 `fmt`：

```python
fmt = logging.Formatter(
    "%(asctime)s  %(levelname)-7s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
color_fmt = _ColorFormatter(
    "%(asctime)s  %(levelname)-7s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

stream_handler = logging.StreamHandler(sys.stderr)
stream_handler.setLevel(root.level)
stream_handler.addFilter(_DEBUGFilter())
stream_handler.setFormatter(color_fmt)        # ← 改这一行
root.addHandler(stream_handler)

# FileHandler 块完全不动，仍 setFormatter(fmt)
```

## Data Model

无新增数据结构、配置项或字段。

## Error Handling

- `_ColorFormatter.format` 内部只做字典查表与字符串拼接，不会引入新异常路径。
- 不捕获 `super().format()` 的异常 —— 与基类语义保持一致。
- 既有 `OSError → 降级为仅 stderr` 路径不变；降级后的 StreamHandler 仍持有
  `_ColorFormatter`，颜色照常工作（满足 R4.1）。

## Testing Strategy

在 `tests/test_v02_optimize.py::TestSetupLogging` 中追加新用例（不修改已有
四个用例，满足 R4.2）：

1. **`test_console_output_is_colored`**
   - 用 `caplog` 不行（caplog 用自己的 handler）。改用：手动构造一条
     `LogRecord`，直接调用 `_ColorFormatter().format(record)`，断言返回值
     以对应级别的 ANSI 前缀开头、以 `\x1b[0m` 结尾。
   - 覆盖 DEBUG/INFO/WARNING/ERROR/CRITICAL 五个级别（参数化或 5 个断言）。

2. **`test_file_output_has_no_ansi`**
   - 在 `tmp_path` 配置 `log_file`，调用 `setup_logging(config)`。
   - 通过 root logger 触发 `INFO`/`ERROR`/`CRITICAL` 三条记录。
   - 关闭/flush 文件 handler 后读文件，断言内容不含字节 `"\x1b["`。
   - 这同时回归保护 R2.1。

3. **`test_stream_handler_uses_color_formatter`**
   - 调用 `setup_logging(config)` 后，在 `root.handlers` 中找
     `StreamHandler`（且非 `FileHandler` —— `FileHandler` 是 `StreamHandler`
     子类，需用 `type(h) is logging.StreamHandler` 精确匹配），断言其
     `formatter` 是 `_ColorFormatter` 实例。
   - 同时断言 `FileHandler` 的 formatter **不是** `_ColorFormatter`。

测试不依赖真实 TTY，也无需 mock `isatty`（按 R3 不引入开关，统一输出 ANSI）。

## Tradeoffs / Notes

- **永远输出 ANSI**：用户明确"无需开关"。在 Windows 现代终端
  (Windows Terminal / VS Code 集成终端 / PowerShell 7+) 中 ANSI 默认启用；
  在被重定向到文件或老旧 cmd.exe 时会看到原始转义码，这是已知取舍。文件
  日志由 FileHandler 单独写，不受影响。
- **不使用第三方库**：`colorama`/`rich` 会更稳健，但违反 R3.2 且对本项目
  显著过度工程。
- **整行包色**而非只染 `levelname`：实现更简单（一次包裹），视觉一致性更好；
  R1 各条款也按"整行"措辞。
