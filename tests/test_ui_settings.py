from pathlib import Path

import pytest

from subforge.ui.settings import UiSettingsStore
from subforge.ui.picker import FakeFilePicker


def test_ui_settings_persists_one_active_movable_library(tmp_path):
    config = tmp_path / "ui.json"
    library = tmp_path / "Library"
    library.mkdir()
    store = UiSettingsStore(config)

    store.set_active_library(library)

    assert UiSettingsStore(config).get_active_library() == library.resolve()


def test_ui_settings_persists_model_cache_and_direct_model_paths(tmp_path):
    store = UiSettingsStore(tmp_path / "ui.json")
    cache = tmp_path / "model-cache"
    direct = tmp_path / "large-v3"
    cache.mkdir()
    direct.mkdir()
    (direct / "model.bin").write_bytes(b"model")
    (direct / "config.json").write_text("{}", encoding="utf-8")

    store.set_models_dir(cache)
    store.set_direct_model_path("large-v3", direct)

    reopened = UiSettingsStore(tmp_path / "ui.json")
    assert reopened.get_models_dir() == cache.resolve()
    assert reopened.get_direct_model_path("large-v3") == direct.resolve()


def test_invalid_direct_model_directory_is_rejected(tmp_path):
    store = UiSettingsStore(tmp_path / "ui.json")
    directory = tmp_path / "not-a-model"
    directory.mkdir()

    try:
        store.set_direct_model_path("large-v3", directory)
    except ValueError as exc:
        assert "model.bin" in str(exc)
    else:
        raise AssertionError("invalid model directory was accepted")


def test_check_model_configuration_reports_direct_dir_cache_and_missing(tmp_path):
    from subforge.ui.checks import check_model_configuration

    direct = tmp_path / "direct-medium"
    direct.mkdir()
    (direct / "model.bin").write_bytes(b"m")
    (direct / "config.json").write_text("{}", encoding="utf-8")

    ok, message = check_model_configuration("medium", tmp_path / "cache", direct)
    assert ok and "直接模型目录可用" in message

    ok, message = check_model_configuration("large-v3", tmp_path / "cache", None)
    assert not ok and "未缓存" in message


def test_ui_settings_persists_proxy_url(tmp_path):
    store = UiSettingsStore(tmp_path / "ui.json")

    store.set_proxy_url("http://127.0.0.1:7890")

    assert UiSettingsStore(tmp_path / "ui.json").get_proxy_url() == "http://127.0.0.1:7890"


def test_invalid_proxy_url_is_rejected(tmp_path):
    store = UiSettingsStore(tmp_path / "ui.json")

    try:
        store.set_proxy_url("127.0.0.1:7890")
    except ValueError as exc:
        assert "http://" in str(exc)
    else:
        raise AssertionError("invalid proxy was accepted")


def test_ui_settings_persists_secret_and_distinct_processing_concurrency(tmp_path):
    store = UiSettingsStore(tmp_path / "ui.json")

    store.set_deepgram_api_key("dg-secret-value-123")
    store.set_asr_concurrency(2)
    store.set_translate_workers(7)

    reopened = UiSettingsStore(tmp_path / "ui.json")
    assert reopened.get_deepgram_api_key() == "dg-secret-value-123"
    assert reopened.get_asr_concurrency() == 2
    assert reopened.get_translate_workers() == 7


def test_ui_settings_persists_last_processing_snapshot(tmp_path):
    store = UiSettingsStore(tmp_path / "ui.json")
    snapshot = {
        "asr_provider": "deepgram",
        "scene": "normal",
        "whisper_model": "medium",
        "llm_profile_id": "profile-1",
        "asr_profile_id": "",
        "merge_profile_id": "",
        "asr_chunk_seconds": 60,
    }

    store.set_last_processing_snapshot(snapshot)

    assert UiSettingsStore(tmp_path / "ui.json").get_last_processing_snapshot() == snapshot


def test_legacy_media_concurrency_migrates_to_asr_concurrency(tmp_path):
    config = tmp_path / "ui.json"
    config.write_text('{"media_concurrency": 3}', encoding="utf-8")

    assert UiSettingsStore(config).get_asr_concurrency() == 3


def test_blank_secret_does_not_overwrite_and_delete_is_explicit(tmp_path):
    store = UiSettingsStore(tmp_path / "ui.json")
    store.set_deepgram_api_key("dg-secret-value-123")

    store.set_deepgram_api_key("")
    assert store.get_deepgram_api_key() == "dg-secret-value-123"
    store.delete_deepgram_api_key()
    assert store.get_deepgram_api_key() == ""


def test_processing_concurrency_values_must_be_positive(tmp_path):
    store = UiSettingsStore(tmp_path / "ui.json")
    for setter in (store.set_asr_concurrency, store.set_translate_workers):
        try:
            setter(0)
        except ValueError as exc:
            assert "at least 1" in str(exc)
        else:
            raise AssertionError("zero concurrency was accepted")


def test_fake_picker_returns_selected_server_side_paths(tmp_path):
    audio = tmp_path / "audio.m4a"
    library = tmp_path / "Library"
    picker = FakeFilePicker(audio=audio, directory=library)

    assert picker.choose_audio() == audio
    assert picker.choose_directory() == library


def test_remote_asr_concurrency_setting_roundtrip(tmp_path):
    """网络 ASR 并发独立于本地 ASR 并发：默认 2、可配置、拒绝非法值。"""
    store = UiSettingsStore(tmp_path / "ui.json")
    assert store.get_remote_asr_concurrency() == 2
    store.set_remote_asr_concurrency(3)
    assert UiSettingsStore(tmp_path / "ui.json").get_remote_asr_concurrency() == 3
    with pytest.raises(ValueError):
        store.set_remote_asr_concurrency(0)


def test_default_processing_snapshot_roundtrip(tmp_path):
    store = UiSettingsStore(tmp_path / "ui.json")
    assert store.get_default_processing_snapshot() is None
    snapshot = {
        "asr_provider": "local",
        "scene": "normal",
        "whisper_model": "large-v3",
        "llm_profile_id": "prof-1",
        "asr_profile_id": "",
        "merge_profile_id": "",
        "asr_chunk_seconds": 90,
    }
    store.set_default_processing_snapshot(snapshot)
    loaded = UiSettingsStore(tmp_path / "ui.json").get_default_processing_snapshot()
    assert loaded == snapshot
