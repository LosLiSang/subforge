from pathlib import Path

import httpx
import pytest

from subforge.asr.deepgram import (
    DeepgramAuthError,
    DeepgramError,
    _build_query_params,
    _build_url,
    _content_type_for_path,
    _entries_from_words,
    _mask_key,
    _parse_response,
    transcribe,
)


class TestDeepgramSkeleton:
    def test_error_types(self):
        assert issubclass(DeepgramAuthError, DeepgramError)

    def test_mask_key_short(self):
        assert _mask_key("abc") == "***"

    def test_mask_key_long(self):
        assert _mask_key("1234567890abcdef") == "1234...cdef"

    def test_build_query_params_defaults(self):
        params = _build_query_params("nova-3", "ja")

        assert ("model", "nova-3") in params
        assert ("language", "ja") in params
        assert ("smart_format", "true") in params
        assert ("punctuate", "true") in params
        assert ("paragraphs", "false") in params

    def test_build_query_params_repeated_keyterms(self):
        params = _build_query_params("nova-3", "ja", ["気付け", "布団"])

        assert params.count(("keyterm", "気付け")) == 1
        assert params.count(("keyterm", "布団")) == 1

    def test_build_url_encodes_keyterms(self):
        url = _build_url("nova-3", "ja", ["気付け", "布団"])

        assert url.startswith("https://api.deepgram.com/v1/listen?")
        assert "model=nova-3" in url
        assert "language=ja" in url
        assert "keyterm=" in url

    def test_content_type_for_path(self):
        assert _content_type_for_path(Path("a.mp3")) == "audio/mpeg"
        assert _content_type_for_path(Path("a.wav")) == "audio/wav"
        assert _content_type_for_path(Path("a.m4a")) == "audio/mp4"
        assert _content_type_for_path(Path("a.flac")) == "audio/flac"
        assert _content_type_for_path(Path("a.mp4")) == "video/mp4"
        assert _content_type_for_path(Path("a.bin")) == "application/octet-stream"


class TestDeepgramParsing:
    def test_entries_from_words_groups_by_punctuation(self):
        entries = _entries_from_words([
            {"word": "社長", "punctuated_word": "社長、", "start": 0.0, "end": 0.4},
            {"word": "お疲れ様です", "punctuated_word": "お疲れ様です。", "start": 0.5, "end": 1.2},
            {"word": "こちら", "punctuated_word": "こちら", "start": 1.4, "end": 1.8},
            {"word": "コーヒーです", "punctuated_word": "コーヒーです。", "start": 1.9, "end": 2.6},
        ])

        assert len(entries) == 2
        assert entries[0].index == 1
        assert entries[0].text == "社長、お疲れ様です。"
        assert entries[0].start == 0.0
        assert entries[0].end == 1.2
        assert entries[1].index == 2
        assert entries[1].text == "こちらコーヒーです。"

    def test_entries_from_words_groups_by_gap(self):
        entries = _entries_from_words([
            {"word": "a", "start": 0.0, "end": 0.5},
            {"word": "b", "start": 0.6, "end": 1.0},
            {"word": "c", "start": 2.0, "end": 2.5},
        ])

        assert [entry.text for entry in entries] == ["ab", "c"]
        assert [entry.index for entry in entries] == [1, 2]

    def test_parse_response_uses_words(self):
        data = {
            "metadata": {"duration": 10.0},
            "results": {
                "channels": [{
                    "alternatives": [{
                        "transcript": "fallback",
                        "words": [
                            {"word": "hello", "start": 0.0, "end": 0.5},
                            {"word": "world", "start": 0.6, "end": 1.0},
                        ],
                    }]
                }]
            },
        }

        entries = _parse_response(data)

        assert len(entries) == 1
        assert entries[0].text == "helloworld"
        assert entries[0].end == 1.0

    def test_parse_response_falls_back_to_transcript(self):
        data = {
            "metadata": {"duration": 3.2},
            "results": {
                "channels": [{
                    "alternatives": [{
                        "transcript": "全文です",
                        "words": [],
                    }]
                }]
            },
        }

        entries = _parse_response(data)

        assert len(entries) == 1
        assert entries[0].text == "全文です"
        assert entries[0].start == 0.0
        assert entries[0].end == 3.2

    def test_parse_response_empty_transcript_raises(self):
        data = {
            "metadata": {"duration": 3.2},
            "results": {
                "channels": [{
                    "alternatives": [{"transcript": "", "words": []}]
                }]
            },
        }

        with pytest.raises(DeepgramError, match="no transcript"):
            _parse_response(data)

    def test_parse_response_missing_alternative_raises(self):
        with pytest.raises(DeepgramError, match="alternatives"):
            _parse_response({"results": {"channels": []}})


def _success_response() -> dict:
    return {
        "metadata": {"duration": 1.0},
        "results": {
            "channels": [{
                "alternatives": [{
                    "transcript": "hello",
                    "words": [{"word": "hello", "start": 0.0, "end": 1.0}],
                }]
            }]
        },
    }


class TestDeepgramTranscribe:
    def test_transcribe_success(self, tmp_path):
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"audio")
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json=_success_response())

        client = httpx.Client(transport=httpx.MockTransport(handler))

        entries = transcribe(audio, "dg-secret-key", client=client, sleep_fn=lambda _: None)

        assert len(entries) == 1
        assert entries[0].text == "hello"
        assert calls[0].headers["Authorization"] == "Token dg-secret-key"
        assert calls[0].headers["Content-Type"] == "audio/mpeg"
        assert "model=nova-3" in str(calls[0].url)
        assert "language=ja" in str(calls[0].url)

    def test_transcribe_missing_key_raises(self, tmp_path):
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"audio")

        with pytest.raises(DeepgramAuthError, match="required"):
            transcribe(audio, "", sleep_fn=lambda _: None)

    def test_transcribe_401_no_retry(self, tmp_path):
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"audio")
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(401, json={"error": "bad key"})

        client = httpx.Client(transport=httpx.MockTransport(handler))

        with pytest.raises(DeepgramAuthError, match="authentication"):
            transcribe(audio, "dg-secret-key", client=client, sleep_fn=lambda _: None)
        assert calls == 1

    def test_transcribe_429_retries_then_success(self, tmp_path):
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"audio")
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls == 1:
                return httpx.Response(429, json={"error": "limited"})
            return httpx.Response(200, json=_success_response())

        client = httpx.Client(transport=httpx.MockTransport(handler))

        entries = transcribe(audio, "dg-secret-key", client=client, sleep_fn=lambda _: None)

        assert len(entries) == 1
        assert calls == 2

    def test_transcribe_5xx_retries_exhausted(self, tmp_path):
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"audio")
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(503, json={"error": "down"})

        client = httpx.Client(transport=httpx.MockTransport(handler))

        with pytest.raises(DeepgramError, match="failed after 3 retries"):
            transcribe(audio, "dg-secret-key", client=client, sleep_fn=lambda _: None)
        assert calls == 3

    def test_transcribe_empty_result_raises(self, tmp_path):
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"audio")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "metadata": {"duration": 1.0},
                "results": {"channels": [{"alternatives": [{"transcript": "", "words": []}]}]},
            })

        client = httpx.Client(transport=httpx.MockTransport(handler))

        with pytest.raises(DeepgramError, match="no transcript"):
            transcribe(audio, "dg-secret-key", client=client, sleep_fn=lambda _: None)

    def test_transcribe_progress_callback(self, tmp_path):
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"audio")
        progress = []

        client = httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=_success_response())
        ))

        transcribe(audio, "dg-secret-key", client=client, sleep_fn=lambda _: None, progress_callback=progress.append)

        assert progress == [1.0]
