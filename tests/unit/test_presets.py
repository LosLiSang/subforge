import pytest

from subforge.presets import resolve_scene


@pytest.mark.parametrize(
    ("requested", "default", "expected"),
    [
        # 表单显式给出合法场景：以表单为准
        ("asmr", "normal", "asmr"),
        ("normal", "asmr", "normal"),
        # 表单未给出（处理对话框选了非 Whisper 引擎时不发送）：回退到设置默认
        ("", "normal", "normal"),
        (None, "asmr", "asmr"),
        # 设置也没有：回退到 asmr（产品核心场景）
        ("", "", "asmr"),
        (None, None, "asmr"),
        # 非法值一律忽略
        ("bogus", "normal", "normal"),
        ("bogus", "bogus", "asmr"),
        # 容忍大小写与空白
        (" ASMR ", "", "asmr"),
    ],
)
def test_resolve_scene(requested, default, expected):
    assert resolve_scene(requested, default) == expected
