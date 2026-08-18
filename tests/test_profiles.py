import json

import pytest

from subforge.ui.profiles import LlmProfileStore, mask_secret


def test_mask_secret_shows_only_safe_edges():
    assert mask_secret("sk-1234567890abcdef") == "sk-1•••••••••••cdef"
    assert mask_secret("short") == "已配置"
    assert mask_secret("") == "未配置"


def test_environment_key_is_resolved_but_never_revealed(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-environment-secret")
    store = LlmProfileStore(tmp_path / "profiles.json")
    profile = store.save("Env", "https://api.example/v1", "chat", "")

    assert store.resolve(profile.profile_id).api_key == "sk-environment-secret"
    assert store.list_public()[0]["api_key_masked"] == "已通过环境变量配置"


def test_profile_persists_independent_proxy_and_tls_settings(tmp_path):
    ca = tmp_path / "ca.pem"
    ca.write_text("certificate", encoding="utf-8")
    store = LlmProfileStore(tmp_path / "profiles.json")

    profile = store.save(
        name="Internal", base_url="https://api.internal/v1", model="chat",
        proxy_url="", verify_tls=False, ca_bundle=str(ca),
    )

    resolved = store.resolve(profile.profile_id)
    assert resolved.proxy_url == ""
    assert resolved.verify_tls is False
    assert resolved.ca_bundle == str(ca)


def test_profile_store_never_returns_key_in_public_view(tmp_path):
    path = tmp_path / "profiles.json"
    store = LlmProfileStore(path)
    profile = store.save(
        name="DeepSeek",
        base_url="https://api.example/v1",
        model="chat",
        api_key="sk-secret-value-1234",
    )

    public = store.list_public()
    raw = path.read_text(encoding="utf-8")

    assert public[0]["profile_id"] == profile.profile_id
    assert public[0]["api_key_masked"].startswith("sk-s")
    assert "sk-secret-value-1234" not in json.dumps(public)
    assert "sk-secret-value-1234" in raw


def test_blank_key_keeps_existing_and_delete_is_explicit(tmp_path):
    store = LlmProfileStore(tmp_path / "profiles.json")
    profile = store.save("Local", "http://127.0.0.1:1234/v1", "model", "secret-value-123")

    store.save("Local 2", "http://127.0.0.1:1234/v1", "model2", "", profile.profile_id)
    assert store.resolve(profile.profile_id).api_key == "secret-value-123"

    store.delete_key(profile.profile_id)
    assert store.resolve(profile.profile_id).api_key == ""


def test_delete_removes_entire_profile(tmp_path):
    store = LlmProfileStore(tmp_path / "profiles.json")
    keep = store.save("Keep", "http://127.0.0.1:1234/v1", "m1", "secret-value-123")
    drop = store.save("Drop", "http://127.0.0.1:5678/v1", "m2", "secret-value-456")

    store.delete(drop.profile_id)

    ids = [p["profile_id"] for p in store.list_public()]
    assert ids == [keep.profile_id]
    with pytest.raises(KeyError):
        store.resolve(drop.profile_id)
    assert "Drop" not in (tmp_path / "profiles.json").read_text(encoding="utf-8")

    with pytest.raises(KeyError):
        store.delete("nonexistent")
