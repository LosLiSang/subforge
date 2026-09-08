from __future__ import annotations

import asyncio
import base64
import inspect
import json
import math
import os
import shutil
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Literal, Protocol
from urllib.parse import quote
from uuid import uuid4

import httpx

from subforge.models import SubtitleEntry
from subforge.segment_processing import (
    ExtractedAudio,
    SegmentCandidate,
    SegmentProcessingError,
    SegmentRequest,
    extract_audio_segment,
)

_FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
from subforge.ui.profiles import mask_secret

GeminiProtocol = Literal["google_native", "openai_compatible"]
GeminiProcessingMode = Literal["transcribe_then_translate", "bilingual_once"]


class GeminiAudioError(SegmentProcessingError):
    pass


@dataclass
class GeminiAudioProfile:
    profile_id: str
    name: str
    protocol: GeminiProtocol
    base_url: str
    model: str
    api_key: str = ""
    default_processing_mode: GeminiProcessingMode = "transcribe_then_translate"
    max_segment_seconds: int = 60
    recognition_prompt: str = ""
    proxy_url: str = ""
    verify_tls: bool = True
    ca_bundle: str = ""


class GeminiAudioProfileStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _load(self) -> list[GeminiAudioProfile]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return [GeminiAudioProfile(**item) for item in data.get("profiles", [])]
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return []

    def _save_all(self, profiles: list[GeminiAudioProfile]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(
            {"schema_version": 1, "profiles": [asdict(profile) for profile in profiles]},
            ensure_ascii=False, indent=2,
        ), encoding="utf-8")
        os.replace(temporary, self.path)

    def save(
        self,
        *,
        name: str,
        protocol: str,
        base_url: str,
        model: str,
        api_key: str = "",
        profile_id: str | None = None,
        default_processing_mode: str = "transcribe_then_translate",
        max_segment_seconds: int = 60,
        recognition_prompt: str = "",
        proxy_url: str = "",
        verify_tls: bool = True,
        ca_bundle: str = "",
    ) -> GeminiAudioProfile:
        if not name.strip() or not base_url.strip() or not model.strip():
            raise ValueError("name, base_url and model are required")
        if protocol not in {"google_native", "openai_compatible"}:
            raise ValueError("unsupported Gemini audio protocol")
        if default_processing_mode not in {"transcribe_then_translate", "bilingual_once"}:
            raise ValueError("unsupported Gemini processing mode")
        if not 1 <= int(max_segment_seconds):
            raise ValueError("max_segment_seconds must be at least 1")
        profiles = self._load()
        existing = next((profile for profile in profiles if profile.profile_id == profile_id), None)
        if existing is None:
            existing = GeminiAudioProfile(
                profile_id or uuid4().hex, name.strip(), protocol, base_url.rstrip("/"), model.strip(), api_key,
            )
            profiles.append(existing)
        existing.name = name.strip()
        existing.protocol = protocol  # type: ignore[assignment]
        existing.base_url = base_url.rstrip("/")
        existing.model = model.strip()
        if api_key:
            existing.api_key = api_key
        existing.default_processing_mode = default_processing_mode  # type: ignore[assignment]
        existing.max_segment_seconds = int(max_segment_seconds)
        existing.recognition_prompt = recognition_prompt.strip()
        existing.proxy_url = proxy_url.strip()
        existing.verify_tls = bool(verify_tls)
        existing.ca_bundle = ca_bundle.strip()
        self._save_all(profiles)
        return existing

    def resolve(self, profile_id: str) -> GeminiAudioProfile:
        profile = next((profile for profile in self._load() if profile.profile_id == profile_id), None)
        if profile is None:
            raise KeyError(profile_id)
        if not profile.api_key and os.environ.get("GEMINI_API_KEY"):
            profile = replace(profile, api_key=os.environ["GEMINI_API_KEY"])
        return profile

    def list_public(self) -> list[dict]:
        result = []
        for profile in self._load():
            item = asdict(profile)
            item.pop("api_key", None)
            item["api_key_masked"] = (
                "已通过环境变量配置"
                if not profile.api_key and os.environ.get("GEMINI_API_KEY")
                else mask_secret(profile.api_key)
            )
            result.append(item)
        return result

    def delete_key(self, profile_id: str) -> None:
        profiles = self._load()
        profile = next((profile for profile in profiles if profile.profile_id == profile_id), None)
        if profile is None:
            raise KeyError(profile_id)
        profile.api_key = ""
        self._save_all(profiles)

    def delete(self, profile_id: str) -> None:
        profiles = self._load()
        remaining = [profile for profile in profiles if profile.profile_id != profile_id]
        if len(remaining) == len(profiles):
            raise KeyError(profile_id)
        self._save_all(remaining)


class GeminiAudioTransport(Protocol):
    async def generate(self, audio: bytes, mime_type: str, prompt: str) -> str: ...


class _BaseGeminiTransport:
    def __init__(
        self,
        profile: GeminiAudioProfile,
        *,
        client: httpx.AsyncClient | None = None,
        retry_delays: tuple[float, ...] = (1, 2),
    ) -> None:
        self.profile = profile
        self._client = client
        self._retry_delays = retry_delays

    def _new_client(self) -> httpx.AsyncClient:
        verify: bool | str = self.profile.verify_tls
        if self.profile.ca_bundle:
            verify = self.profile.ca_bundle
        return httpx.AsyncClient(
            timeout=120,
            proxy=self.profile.proxy_url or None,
            verify=verify,
            trust_env=False,
        )

    async def _post(self, url: str, *, headers: dict, body: dict, parser: Callable[[dict], str]) -> str:
        if not self.profile.api_key:
            raise GeminiAudioError("Gemini 音频配置缺少 API Key")
        client = self._client or self._new_client()
        close = self._client is None
        last_error: Exception | None = None
        try:
            attempts = len(self._retry_delays) + 1
            for attempt in range(attempts):
                try:
                    response = await client.post(url, headers=headers, json=body)
                    if response.status_code == 401:
                        raise GeminiAudioError("Gemini 音频鉴权失败（401）")
                    if response.status_code == 429 or response.status_code >= 500:
                        raise httpx.HTTPStatusError("retryable Gemini response", request=response.request, response=response)
                    response.raise_for_status()
                    text = parser(response.json()).strip()
                    if not text:
                        raise GeminiAudioError("Gemini 音频模型返回空内容")
                    return text
                except GeminiAudioError as exc:
                    last_error = exc
                    if "鉴权失败" in str(exc):
                        raise
                except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError, ValueError, KeyError, TypeError) as exc:
                    last_error = exc
                    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code not in {429, 500, 502, 503, 504}:
                        break
                if attempt < len(self._retry_delays):
                    await asyncio.sleep(self._retry_delays[attempt])
            detail = str(last_error).strip() if last_error else "unknown error"
            raise GeminiAudioError(f"Gemini 音频请求失败：{detail[:300]}") from last_error
        finally:
            if close:
                await client.aclose()


class GoogleGeminiTransport(_BaseGeminiTransport):
    async def generate(self, audio: bytes, mime_type: str, prompt: str) -> str:
        base = self.profile.base_url.rstrip("/")
        prefix = base if base.endswith("/v1beta") else f"{base}/v1beta"
        model = quote(self.profile.model, safe="-._")
        url = f"{prefix}/models/{model}:generateContent"
        body = {
            "contents": [{"role": "user", "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": mime_type, "data": base64.b64encode(audio).decode("ascii")}},
            ]}],
            "generationConfig": {"temperature": 0},
        }

        def parse(data: dict) -> str:
            parts = data["candidates"][0]["content"]["parts"]
            return "\n".join(str(part.get("text", "")) for part in parts if part.get("text"))

        return await self._post(
            url,
            headers={"x-goog-api-key": self.profile.api_key, "content-type": "application/json"},
            body=body,
            parser=parse,
        )


class OpenAICompatibleAudioTransport(_BaseGeminiTransport):
    async def generate(self, audio: bytes, mime_type: str, prompt: str) -> str:
        audio_format = "wav" if mime_type == "audio/wav" else mime_type.split("/")[-1]
        url = f"{self.profile.base_url.rstrip('/')}/chat/completions"
        body = {
            "model": self.profile.model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "input_audio", "input_audio": {
                    "data": base64.b64encode(audio).decode("ascii"), "format": audio_format,
                }},
            ]}],
            "temperature": 0,
        }

        def parse(data: dict) -> str:
            content = data["choices"][0]["message"]["content"]
            if isinstance(content, list):
                return "\n".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
            return str(content or "")

        return await self._post(
            url,
            headers={"Authorization": f"Bearer {self.profile.api_key}", "Content-Type": "application/json"},
            body=body,
            parser=parse,
        )


TranslateFn = Callable[[list[SubtitleEntry], str, str], Awaitable[list[SubtitleEntry]] | list[SubtitleEntry]]


def detect_speech_regions(clip_path: Path, clip_duration: float) -> list[tuple[float, float]]:
    """用 ffmpeg silencedetect 找出语音区间（时间轴由 SubForge 产生，不依赖模型）。"""
    result = subprocess.run(
        [_FFMPEG, "-i", str(clip_path),
         "-af", "silencedetect=noise=-35dB:d=0.4", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    silences: list[tuple[float, float]] = []
    start: float | None = None
    for line in (result.stderr or "").splitlines():
        if "silence_start:" in line:
            try:
                start = float(line.rsplit(":", 1)[1].strip().split(" ")[0])
            except ValueError:
                start = None
        elif "silence_end:" in line and start is not None:
            try:
                end = float(line.rsplit(":", 1)[1].strip().split(" ")[0])
                silences.append((max(0.0, start), min(clip_duration, end)))
            except ValueError:
                pass
            start = None
    regions: list[tuple[float, float]] = []
    cursor = 0.0
    for silence_start, silence_end in silences:
        if silence_start - cursor > 0.05:
            regions.append((cursor, silence_start))
        cursor = max(cursor, silence_end)
    if clip_duration - cursor > 0.05:
        regions.append((cursor, clip_duration))
    return [region for region in regions if region[1] - region[0] > 0.05]


def plan_chunks_from_regions(
    regions: list[tuple[float, float]],
    max_seconds: float,
    clip_duration: float,
) -> list[tuple[float, float]]:
    """单段语音超过上限时均匀切分；不跨静音合并，保持语音边界。"""
    chunks: list[tuple[float, float]] = []
    for start, end in regions:
        span = end - start
        if span <= max_seconds:
            chunks.append((start, end))
            continue
        parts = math.ceil(span / max_seconds)
        bounds = [start + span * index / parts for index in range(parts + 1)]
        chunks.extend(zip(bounds, bounds[1:]))
    return [
        (round(max(0.0, start), 3), round(min(clip_duration, end), 3))
        for start, end in chunks
    ]


def cut_wav_bytes(clip_path: Path, start: float, end: float) -> bytes:
    """从 16k mono wav 截取 [start, end) 并返回 wav 字节。"""
    result = subprocess.run(
        [_FFMPEG, "-y", "-i", str(clip_path), "-ss", f"{start:.3f}",
         "-t", f"{end - start:.3f}", "-c:a", "pcm_s16le", "-f", "wav", "-"],
        capture_output=True, timeout=120,
    )
    if result.returncode != 0 or not result.stdout:
        raise GeminiAudioError(f"片段切块失败（ffmpeg {result.returncode}）")
    return result.stdout


class GeminiAudioAdapter:
    def __init__(
        self,
        profile: GeminiAudioProfile,
        transport: GeminiAudioTransport,
        *,
        extractor: Callable[[SegmentRequest], ExtractedAudio] = extract_audio_segment,
        translate_fn: TranslateFn | None = None,
        speech_regions: Callable[[Path, float], list[tuple[float, float]]] = detect_speech_regions,
        chunk_cutter: Callable[[Path, float, float], bytes] = cut_wav_bytes,
    ) -> None:
        self.profile = profile
        self.transport = transport
        self._extractor = extractor
        self._translate = translate_fn
        self._speech_regions = speech_regions
        self._chunk_cutter = chunk_cutter

    async def process(self, request: SegmentRequest) -> SegmentCandidate:
        duration = request.target_end - request.target_start
        if duration <= 0:
            raise ValueError("片段时间范围无效")
        mode = request.processing_mode or self.profile.default_processing_mode
        if mode not in {"transcribe_then_translate", "bilingual_once"}:
            raise ValueError("未知 Gemini 处理模式")
        extracted = await asyncio.to_thread(self._extractor, request)
        try:
            chunks, detection_failed = await self._plan_chunks(request, extracted)
            extra = request.recognition_prompt.strip() or self.profile.recognition_prompt
            context = f"\n可能出现的专有词或上下文：{extra}" if extra else ""
            source_entries: list[SubtitleEntry] = []
            target_entries: list[SubtitleEntry] = []
            skipped = 0
            for chunk_index, (chunk_start, chunk_end) in enumerate(chunks):
                if len(chunks) == 1:
                    audio = await asyncio.to_thread(extracted.path.read_bytes)
                else:
                    audio = await asyncio.to_thread(self._chunk_cutter, extracted.path, chunk_start, chunk_end)
                if mode == "bilingual_once":
                    prompt = (
                        f"请逐字理解这段{request.source_language}音频，并翻译为{request.target_language}。"
                        "只输出一个 JSON 对象，严格包含 source_text 和 target_text 两个非空字符串；"
                        "不要输出时间戳、Markdown 或解释。" + context
                    )
                    raw = await self.transport.generate(audio, "audio/wav", prompt)
                    source_text, target_text = self._parse_bilingual(raw)
                else:
                    prompt = (
                        f"请把这段音频逐字转写为{request.source_language}文本。"
                        "只输出转写正文，不要翻译，不要时间戳，不要 Markdown 或解释。" + context
                    )
                    source_text = (await self.transport.generate(audio, "audio/wav", prompt)).strip()
                    target_text = ""
                if not source_text:
                    skipped += 1
                    continue
                index = len(source_entries) + 1
                # 候选时间钳制到目标选区（块可能包含前后上下文）
                abs_start = max(request.target_start, extracted.start + chunk_start)
                abs_end = min(request.target_end, extracted.start + chunk_end)
                if abs_start >= abs_end:
                    skipped += 1
                    continue
                source_entries.append(SubtitleEntry(
                    index,
                    round(abs_start, 3),
                    round(abs_end, 3),
                    source_text,
                ))
                if target_text:
                    target_entries.append(SubtitleEntry(
                        index,
                        round(abs_start, 3),
                        round(abs_end, 3),
                        target_text,
                    ))
            if not source_entries:
                raise GeminiAudioError("Gemini 未在片段中识别出任何文本")
            warnings: list[str] = []
            if len(chunks) > 1:
                warnings.append(f"长片段已按语音区间切分为 {len(chunks)} 块分别识别" + (f"，跳过 {skipped} 块空结果" if skipped else ""))
            if detection_failed:
                warnings.append("语音区间检测失败，已回退为整段一次识别")
            if mode == "transcribe_then_translate":
                if self._translate is None:
                    raise GeminiAudioError("转写后翻译模式缺少文本翻译配置")
                translated = self._translate(source_entries, request.source_language, request.target_language)
                target_entries = await translated if inspect.isawaitable(translated) else translated
                if len(target_entries) != len(source_entries) or any(not entry.text.strip() for entry in target_entries):
                    raise GeminiAudioError("文本 LLM 未返回完整片段译文")
                target_entries = [
                    SubtitleEntry(entry.index, source_entries[entry.index - 1].start, source_entries[entry.index - 1].end, entry.text.strip())
                    for entry in target_entries
                ]
            elif len(target_entries) != len(source_entries):
                raise GeminiAudioError("Gemini 双语结果部分缺失")
            return SegmentCandidate(
                source_entries=source_entries,
                target_entries=target_entries,
                processor="gemini",
                target_start=request.target_start,
                target_end=request.target_end,
                warnings=(
                    "Gemini 只生成文本，候选沿用 SubForge 选区时间轴",
                    *warnings,
                ),
            )
        finally:
            extracted.cleanup()

    async def _plan_chunks(
        self,
        request: SegmentRequest,
        extracted: ExtractedAudio,
    ) -> tuple[list[tuple[float, float]], bool]:
        """长片段按语音区间切成不超过 Profile 上限的块；失败时退回单块整段。"""
        clip_duration = extracted.end - extracted.start
        if clip_duration <= self.profile.max_segment_seconds:
            return [(0.0, clip_duration)], False
        try:
            regions = await asyncio.to_thread(self._speech_regions, extracted.path, clip_duration)
            chunks = plan_chunks_from_regions(regions, self.profile.max_segment_seconds, clip_duration)
        except Exception:
            return [(0.0, clip_duration)], True
        if not chunks:
            return [(0.0, clip_duration)], True
        return chunks, False

    @staticmethod
    def _parse_bilingual(raw: str) -> tuple[str, str]:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        try:
            data = json.loads(text)
            source = str(data.get("source_text", "")).strip()
            target = str(data.get("target_text", "")).strip()
        except (ValueError, TypeError, AttributeError) as exc:
            raise GeminiAudioError("Gemini 双语结果不是有效 JSON") from exc
        if not source or not target:
            raise GeminiAudioError("Gemini 双语结果缺少源文或译文")
        return source, target
