# ASMR 预设只作用于本地 faster-whisper（VAD / 静音阈值 / 响度预处理 / 双声道拆分）；
# Deepgram 与音频模型 Profile 不读取这些参数。
ASMR_PRESET = {
    "vad_threshold": 0.2,
    "vad_min_speech_duration_ms": 100,
    "vad_min_silence_duration_ms": 300,
    "vad_speech_pad_ms": 600,
    "vad_max_speech_duration_s": 20.0,
    "condition_on_previous_text": False,
    "no_speech_threshold": 0.3,
    "preprocess_audio": True,
}

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
