from __future__ import annotations

import json

from subforge.ui.model_profiles import ModelProfileStore


def _write(path, profiles):
    path.write_text(json.dumps({"schema_version": 1, "profiles": profiles}), encoding="utf-8")


def test_save_and_resolve_with_capabilities(tmp_path):
    store = ModelProfileStore(tmp_path / "model-profiles.json")
    profile = store.save(
        name="Gemini Flash",
        base_url="https://generativelanguage.googleapis.com",
        model="gemini-3.6-flash",
        api_key="secret-key",
        protocol="google_native",
        capabilities=["transcribe", "translate"],
        max_request_seconds=45,
        temperature=0.2,
    )
    assert profile.supports("transcribe") and profile.supports("translate")
    assert not profile.supports("merge")

    resolved = store.resolve(profile.profile_id)
    assert resolved.api_key == "secret-key"
    assert resolved.max_request_seconds == 45
    assert resolved.temperature == 0.2

    public = store.list_public()
    assert public[0]["api_key_masked"]
    assert "api_key" not in public[0]
    assert public[0]["capabilities"] == ["transcribe", "translate"]


def test_list_for_filters_by_capability(tmp_path):
    store = ModelProfileStore(tmp_path / "model-profiles.json")
    store.save(name="ASR", base_url="http://a", model="m1", capabilities=["transcribe"])
    store.save(name="Translate", base_url="http://b", model="m2", capabilities=["translate"])
    store.save(name="Merge", base_url="http://c", model="m3", capabilities=["merge"])

    assert [item["name"] for item in store.list_for("transcribe")] == ["ASR"]
    assert [item["name"] for item in store.list_for("translate")] == ["Translate"]
    assert [item["name"] for item in store.list_for("merge")] == ["Merge"]


def test_save_requires_at_least_one_capability(tmp_path):
    store = ModelProfileStore(tmp_path / "model-profiles.json")
    try:
        store.save(name="x", base_url="http://x", model="m", capabilities=[])
    except ValueError as exc:
        assert "能力" in str(exc)
    else:  # pragma: no cover - should not reach
        raise AssertionError("expected ValueError for empty capabilities")


def test_save_rejects_unknown_protocol(tmp_path):
    store = ModelProfileStore(tmp_path / "model-profiles.json")
    try:
        store.save(name="x", base_url="http://x", model="m", protocol="grpc", capabilities=["translate"])
    except ValueError as exc:
        assert "protocol" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for unknown protocol")


def test_migrates_legacy_llm_and_gemini_profiles(tmp_path):
    llm_path = tmp_path / "llm-profiles.json"
    gemini_path = tmp_path / "gemini-audio-profiles.json"
    _write(llm_path, [{
        "profile_id": "llm1", "name": "GLM", "base_url": "https://api.example/v1",
        "model": "glm-5.3-flash", "api_key": "llm-key", "proxy_url": "", "verify_tls": True, "ca_bundle": "",
    }])
    _write(gemini_path, [{
        "profile_id": "gem1", "name": "Gemini Audio", "protocol": "google_native",
        "base_url": "https://generativelanguage.googleapis.com", "model": "gemini-3.6-flash",
        "api_key": "gem-key", "default_processing_mode": "transcribe_then_translate",
        "max_segment_seconds": 90, "recognition_prompt": "", "temperature": 0.0,
        "bilingual_prompt": "", "transcribe_prompt": "听写提示", "proxy_url": "",
        "verify_tls": True, "ca_bundle": "",
    }])

    target = tmp_path / "model-profiles.json"
    store = ModelProfileStore(target, legacy_llm_path=llm_path, legacy_gemini_path=gemini_path)
    profiles = {profile.profile_id: profile for profile in store._load()}

    assert set(profiles) == {"llm1", "gem1"}
    assert profiles["llm1"].capabilities == ["translate"]
    assert profiles["llm1"].api_key == "llm-key"
    gemini = profiles["gem1"]
    assert gemini.capabilities == ["transcribe", "translate"]
    assert gemini.protocol == "google_native"
    assert gemini.max_request_seconds == 90
    assert gemini.transcribe_prompt == "听写提示"

    # 迁移结果落盘；再次加载不会重复迁移
    assert target.exists()
    assert len(store._load()) == 2


def test_migration_runs_only_when_target_missing(tmp_path):
    target = tmp_path / "model-profiles.json"
    store = ModelProfileStore(target)
    store.save(name="only", base_url="http://x", model="m", capabilities=["translate"])

    legacy = tmp_path / "llm-profiles.json"
    _write(legacy, [{"profile_id": "legacy", "name": "Legacy", "base_url": "http://y", "model": "m2"}])
    store_with_legacy = ModelProfileStore(target, legacy_llm_path=legacy)
    names = {profile.name for profile in store_with_legacy._load()}
    assert names == {"only"}


def test_delete_and_delete_key(tmp_path):
    store = ModelProfileStore(tmp_path / "model-profiles.json")
    profile = store.save(name="p", base_url="http://x", model="m", api_key="k", capabilities=["translate"])
    store.delete_key(profile.profile_id)
    assert store.resolve(profile.profile_id).api_key == ""
    store.delete(profile.profile_id)
    assert store.list_public() == []
