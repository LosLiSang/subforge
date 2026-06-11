import json
from pathlib import Path

from subforge.config import Config
from subforge.models import Job, SubtitleEntry
from subforge.resume import (
    ResumeState,
    ResumeStateError,
    ResumeStore,
    SCHEMA_VERSION,
    read_reusable_srt,
)
from subforge.translate.srt_io import write_srt


class TestResumeStore:
    def test_init_creates_jobs_dir(self, tmp_path):
        jobs_dir = tmp_path / "jobs"
        assert not jobs_dir.exists()

        store = ResumeStore(jobs_dir)

        assert store.jobs_dir == jobs_dir
        assert jobs_dir.exists()
        assert jobs_dir.is_dir()

    def test_build_job_key_is_stable_for_same_file(self, tmp_path):
        media = tmp_path / "audio.m4a"
        media.write_text("audio", encoding="utf-8")
        job = Job(file_path=media)
        config = Config()
        store = ResumeStore(tmp_path / "jobs")

        key1 = store.build_job_key(job, config)
        key2 = store.build_job_key(job, config)

        assert key1 == key2
        assert len(key1) == 64

    def test_build_job_key_differs_for_different_files(self, tmp_path):
        media1 = tmp_path / "audio1.m4a"
        media2 = tmp_path / "audio2.m4a"
        media1.write_text("audio", encoding="utf-8")
        media2.write_text("audio", encoding="utf-8")
        config = Config()
        store = ResumeStore(tmp_path / "jobs")

        key1 = store.build_job_key(Job(file_path=media1), config)
        key2 = store.build_job_key(Job(file_path=media2), config)

        assert key1 != key2

    def test_build_job_key_differs_for_different_languages(self, tmp_path):
        media = tmp_path / "audio.m4a"
        media.write_text("audio", encoding="utf-8")
        config = Config()
        store = ResumeStore(tmp_path / "jobs")

        key1 = store.build_job_key(Job(file_path=media, source_lang="ja", target_lang="zh"), config)
        key2 = store.build_job_key(Job(file_path=media, source_lang="en", target_lang="zh"), config)
        key3 = store.build_job_key(Job(file_path=media, source_lang="ja", target_lang="en"), config)

        assert key1 != key2
        assert key1 != key3

    def test_build_job_key_differs_for_asr_provider(self, tmp_path):
        media = tmp_path / "audio.m4a"
        media.write_text("audio", encoding="utf-8")
        job = Job(file_path=media)
        store = ResumeStore(tmp_path / "jobs")

        key1 = store.build_job_key(job, Config(asr_provider="local"))
        key2 = store.build_job_key(job, Config(asr_provider="deepgram"))

        assert key1 != key2

    def test_build_job_key_differs_for_deepgram_model(self, tmp_path):
        media = tmp_path / "audio.m4a"
        media.write_text("audio", encoding="utf-8")
        job = Job(file_path=media)
        store = ResumeStore(tmp_path / "jobs")

        key1 = store.build_job_key(job, Config(asr_provider="deepgram", deepgram_model="nova-2"))
        key2 = store.build_job_key(job, Config(asr_provider="deepgram", deepgram_model="nova-3"))

        assert key1 != key2

    def test_build_job_key_differs_for_deepgram_keyterms(self, tmp_path):
        media = tmp_path / "audio.m4a"
        media.write_text("audio", encoding="utf-8")
        job = Job(file_path=media)
        store = ResumeStore(tmp_path / "jobs")

        key1 = store.build_job_key(job, Config(asr_provider="deepgram", deepgram_keyterms=["社長"]))
        key2 = store.build_job_key(job, Config(asr_provider="deepgram", deepgram_keyterms=["布団"]))

        assert key1 != key2

    def test_state_path_uses_job_key(self, tmp_path):
        media = tmp_path / "audio.m4a"
        media.write_text("audio", encoding="utf-8")
        job = Job(file_path=media)
        config = Config()
        store = ResumeStore(tmp_path / "jobs")

        path = store.state_path(job, config)

        assert path.parent == tmp_path / "jobs"
        assert path.name == f"{store.build_job_key(job, config)}.json"

    def test_create_state_contains_expected_fingerprints(self, tmp_path):
        media = tmp_path / "audio.m4a"
        media.write_text("audio", encoding="utf-8")
        job = Job(file_path=media, source_lang="ja", target_lang="zh", model_size="medium")
        config = Config(batch_size=20, context_size=10, llm_model="gpt-4o")
        store = ResumeStore(tmp_path / "jobs")

        state = store.create(job, config, tmp_path / "audio.srt", tmp_path / "audio_zh.srt")

        assert state.schema_version == SCHEMA_VERSION
        assert state.job_key == store.build_job_key(job, config)
        assert state.media["path"] == str(media.resolve())
        assert state.media["size"] == media.stat().st_size
        assert state.media["mtime_ns"] == media.stat().st_mtime_ns
        assert state.config_fingerprint == {
            "asr_provider": "local",
            "source_lang": "ja",
            "target_lang": "zh",
            "asr_model": "medium",
            "deepgram_model": "nova-3",
            "deepgram_keyterms": [],
            "batch_size": 20,
            "context_size": 10,
            "llm_model": "gpt-4o",
        }

    def test_save_and_load_matching_state(self, tmp_path):
        media = tmp_path / "audio.m4a"
        media.write_text("audio", encoding="utf-8")
        job = Job(file_path=media)
        config = Config()
        store = ResumeStore(tmp_path / "jobs")
        state = store.create(job, config, tmp_path / "audio.srt", tmp_path / "audio_zh.srt")

        store.save(state)
        loaded = store.load(job, config)

        assert loaded is not None
        assert loaded.job_key == state.job_key
        assert loaded.media == state.media
        assert loaded.config_fingerprint == state.config_fingerprint

    def test_load_missing_state_returns_none(self, tmp_path):
        media = tmp_path / "audio.m4a"
        media.write_text("audio", encoding="utf-8")
        store = ResumeStore(tmp_path / "jobs")

        assert store.load(Job(file_path=media), Config()) is None

    def test_load_damaged_json_returns_none(self, tmp_path):
        media = tmp_path / "audio.m4a"
        media.write_text("audio", encoding="utf-8")
        job = Job(file_path=media)
        config = Config()
        store = ResumeStore(tmp_path / "jobs")
        store.state_path(job, config).write_text("{not-json", encoding="utf-8")

        assert store.load(job, config) is None

    def test_load_config_mismatch_returns_none(self, tmp_path):
        media = tmp_path / "audio.m4a"
        media.write_text("audio", encoding="utf-8")
        job = Job(file_path=media)
        store = ResumeStore(tmp_path / "jobs")
        state = store.create(job, Config(llm_model="gpt-4o"), tmp_path / "audio.srt", tmp_path / "audio_zh.srt")
        store.save(state)

        assert store.load(job, Config(llm_model="different-model")) is None

    def test_load_api_key_change_still_matches(self, tmp_path):
        media = tmp_path / "audio.m4a"
        media.write_text("audio", encoding="utf-8")
        job = Job(file_path=media)
        store = ResumeStore(tmp_path / "jobs")
        config1 = Config(asr_provider="deepgram", deepgram_api_key="dg-old")
        config2 = Config(asr_provider="deepgram", deepgram_api_key="dg-new")
        state = store.create(job, config1, tmp_path / "audio.srt", tmp_path / "audio_zh.srt")
        store.save(state)

        loaded = store.load(job, config2)

        assert loaded is not None
        assert loaded.job_key == state.job_key

    def test_load_media_mismatch_returns_none(self, tmp_path):
        media = tmp_path / "audio.m4a"
        media.write_text("audio", encoding="utf-8")
        job = Job(file_path=media)
        config = Config()
        store = ResumeStore(tmp_path / "jobs")
        state = store.create(job, config, tmp_path / "audio.srt", tmp_path / "audio_zh.srt")
        store.save(state)
        media.write_text("changed audio", encoding="utf-8")

        assert store.load(job, config) is None

    def test_saved_state_does_not_include_api_key(self, tmp_path):
        media = tmp_path / "audio.m4a"
        media.write_text("audio", encoding="utf-8")
        job = Job(file_path=media)
        config = Config(llm_api_key="sk-secret-value")
        store = ResumeStore(tmp_path / "jobs")
        state = store.create(job, config, tmp_path / "audio.srt", tmp_path / "audio_zh.srt")

        store.save(state)
        content = store.state_path(job, config).read_text(encoding="utf-8")
        data = json.loads(content)

        assert "sk-secret-value" not in content
        assert "llm_api_key" not in content
        assert data["config_fingerprint"]["llm_model"] == config.llm_model

    def test_saved_state_does_not_include_deepgram_api_key(self, tmp_path):
        media = tmp_path / "audio.m4a"
        media.write_text("audio", encoding="utf-8")
        job = Job(file_path=media)
        config = Config(asr_provider="deepgram", deepgram_api_key="dg-secret-value")
        store = ResumeStore(tmp_path / "jobs")
        state = store.create(job, config, tmp_path / "audio.srt", tmp_path / "audio_zh.srt")

        store.save(state)
        content = store.state_path(job, config).read_text(encoding="utf-8")

        assert "dg-secret-value" not in content
        assert "deepgram_api_key" not in content

    def test_mark_asr_done_persists(self, tmp_path):
        media = tmp_path / "audio.m4a"
        media.write_text("audio", encoding="utf-8")
        job = Job(file_path=media)
        config = Config()
        store = ResumeStore(tmp_path / "jobs")
        state = store.create(job, config, tmp_path / "audio.srt", tmp_path / "audio_zh.srt")

        store.mark_asr_done(state)
        loaded = store.load(job, config)

        assert loaded is not None
        assert loaded.asr["status"] == "done"

    def test_save_batch_persists_entries(self, tmp_path):
        media = tmp_path / "audio.m4a"
        media.write_text("audio", encoding="utf-8")
        job = Job(file_path=media)
        config = Config()
        store = ResumeStore(tmp_path / "jobs")
        state = store.create(job, config, tmp_path / "audio.srt", tmp_path / "audio_zh.srt")

        store.save_batch(
            state,
            batch_index=0,
            entries=[
                SubtitleEntry(index=1, start=0.0, end=1.0, text="你好"),
                SubtitleEntry(index=2, start=1.0, end=2.0, text="世界"),
            ],
            total_batches=2,
        )
        loaded = store.load(job, config)

        assert loaded is not None
        assert loaded.translation["status"] == "partial"
        assert loaded.translation["total_batches"] == 2
        assert loaded.translation["completed_batches"]["0"][0]["text"] == "你好"
        assert loaded.translation["completed_batches"]["0"][1]["index"] == 2

    def test_save_multiple_batches_accumulates(self, tmp_path):
        media = tmp_path / "audio.m4a"
        media.write_text("audio", encoding="utf-8")
        job = Job(file_path=media)
        config = Config()
        store = ResumeStore(tmp_path / "jobs")
        state = store.create(job, config, tmp_path / "audio.srt", tmp_path / "audio_zh.srt")

        store.save_batch(state, 0, [SubtitleEntry(index=1, start=0.0, end=1.0, text="a")], 2)
        store.save_batch(state, 1, [SubtitleEntry(index=2, start=1.0, end=2.0, text="b")], 2)
        loaded = store.load(job, config)

        assert loaded is not None
        assert set(loaded.translation["completed_batches"]) == {"0", "1"}

    def test_mark_translation_done_persists_completed_batches(self, tmp_path):
        media = tmp_path / "audio.m4a"
        media.write_text("audio", encoding="utf-8")
        job = Job(file_path=media)
        config = Config()
        store = ResumeStore(tmp_path / "jobs")
        state = store.create(job, config, tmp_path / "audio.srt", tmp_path / "audio_zh.srt")
        store.save_batch(state, 0, [SubtitleEntry(index=1, start=0.0, end=1.0, text="a")], 1)

        store.mark_translation_done(state)
        loaded = store.load(job, config)

        assert loaded is not None
        assert loaded.translation["status"] == "done"
        assert "0" in loaded.translation["completed_batches"]

    def test_saved_batches_survive_without_done_marker(self, tmp_path):
        media = tmp_path / "audio.m4a"
        media.write_text("audio", encoding="utf-8")
        job = Job(file_path=media)
        config = Config()
        store = ResumeStore(tmp_path / "jobs")
        state = store.create(job, config, tmp_path / "audio.srt", tmp_path / "audio_zh.srt")

        store.save_batch(state, 0, [SubtitleEntry(index=1, start=0.0, end=1.0, text="a")], 2)
        loaded = store.load(job, config)

        assert loaded is not None
        assert loaded.translation["status"] == "partial"
        assert loaded.translation["completed_batches"]["0"][0]["text"] == "a"


class TestResumeState:
    def test_create_minimal_state(self):
        state = ResumeState(
            schema_version=SCHEMA_VERSION,
            job_key="abc",
            media={"path": "audio.m4a"},
            config_fingerprint={"source_lang": "ja", "target_lang": "zh"},
            paths={"source_srt": "audio.srt", "target_srt": "audio_zh.srt"},
        )

        assert state.schema_version == 1
        assert state.asr["status"] == "pending"
        assert state.translation["status"] == "pending"
        assert state.translation["completed_batches"] == {}

    def test_error_type_exists(self):
        assert issubclass(ResumeStateError, Exception)


class TestReadReusableSrt:
    def test_valid_srt_returns_entries(self, tmp_path):
        path = tmp_path / "audio.srt"
        write_srt(
            [
                SubtitleEntry(index=1, start=0.0, end=1.0, text="a"),
                SubtitleEntry(index=2, start=1.0, end=2.0, text="b"),
            ],
            path,
        )

        entries = read_reusable_srt(path)

        assert entries is not None
        assert [entry.text for entry in entries] == ["a", "b"]

    def test_empty_srt_returns_none(self, tmp_path):
        path = tmp_path / "empty.srt"
        path.write_text("", encoding="utf-8")

        assert read_reusable_srt(path) is None

    def test_invalid_format_returns_none(self, tmp_path):
        path = tmp_path / "bad.srt"
        path.write_text("not an srt", encoding="utf-8")

        assert read_reusable_srt(path) is None

    def test_invalid_timing_returns_none(self, tmp_path):
        path = tmp_path / "bad-time.srt"
        write_srt([SubtitleEntry(index=1, start=2.0, end=1.0, text="bad")], path)

        assert read_reusable_srt(path) is None

    def test_overlapping_timing_returns_none(self, tmp_path):
        path = tmp_path / "overlap.srt"
        write_srt(
            [
                SubtitleEntry(index=1, start=0.0, end=2.0, text="a"),
                SubtitleEntry(index=2, start=1.5, end=3.0, text="b"),
            ],
            path,
        )

        assert read_reusable_srt(path) is None
