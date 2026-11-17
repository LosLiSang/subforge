# 场景标识（云端 ASR 不使用本地 Whisper VAD 参数）
ASMR_PRESET: dict[str, object] = {}

SCENES = ("asmr", "normal")
DEFAULT_SCENE = "asmr"


def resolve_scene(requested: str | None, default: str | None) -> str:
    """表单显式给出的合法场景优先，其次是设置里的默认场景，最后回退到 asmr。

    处理对话框只在选择本地 Whisper 时显示场景选项，其余引擎不发送该字段，
    此时必须沿用设置默认，而不是静默降级为 normal。
    """
    for candidate in (requested, default):
        value = (candidate or "").strip().lower()
        if value in SCENES:
            return value
    return DEFAULT_SCENE
