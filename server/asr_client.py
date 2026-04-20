from __future__ import annotations

import io
import os
import re
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, List

import numpy as np

from audio_utils import decode_remote_chunk_to_pcm, extract_remote_chunk_to_flac_bytes

try:
    from faster_whisper import WhisperModel
except Exception:
    WhisperModel = None

try:
    from openai import OpenAI, RateLimitError
except Exception:
    OpenAI = None
    RateLimitError = None


@dataclass(slots=True)
class TranscriptSegment:
    start: float
    end: float
    text: str
    is_partial: bool = False


class ASRUnavailableError(RuntimeError):
    pass


@lru_cache(maxsize=4)
def get_model(model_size: str, compute_type: str) -> Any:
    if WhisperModel is None:
        raise ASRUnavailableError(
            "faster-whisper is not installed. Install dependencies from requirements.txt first."
        )
    return WhisperModel(model_size, compute_type=compute_type)


def parse_wait_seconds(message: str) -> float:
    match = re.search(r"Please try again in ([0-9]+)m([0-9]+(?:\.[0-9]+)?)s", message)
    if match:
        return int(match.group(1)) * 60 + float(match.group(2)) + 1.0
    match = re.search(r"Please try again in ([0-9]+(?:\.[0-9]+)?)s", message)
    if match:
        return float(match.group(1)) + 1.0
    return 60.0


def collect_groq_api_keys() -> list[str]:
    keys: list[str] = []
    local_key_files = [
        Path.cwd() / "groq_api_keys.txt",
        Path(__file__).resolve().with_name("groq_api_keys.txt"),
    ]

    for key_file in local_key_files:
        if not key_file.exists():
            continue
        for line in key_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                keys.append(line)

    env_multi = os.environ.get("GROQ_API_KEYS")
    if env_multi:
        keys.extend([key.strip() for key in env_multi.split(",") if key.strip()])

    env_single = os.environ.get("GROQ_API_KEY")
    if env_single and env_single.strip():
        keys.append(env_single.strip())

    deduped: list[str] = []
    seen = set()
    for key in keys:
        if key not in seen:
            seen.add(key)
            deduped.append(key)
    return deduped


class BaseASRClient:
    provider_name = "unknown"

    def transcribe_remote_chunk(
        self,
        media_url: str,
        *,
        start_time: float,
        duration: float,
        headers: dict[str, str] | None = None,
        language: str = "zh",
        initial_prompt: str = "",
    ) -> List[TranscriptSegment]:
        raise NotImplementedError


class FasterWhisperClient(BaseASRClient):
    provider_name = "faster-whisper"

    def __init__(self, model_size: str = "small", compute_type: str = "auto") -> None:
        self.model_size = model_size
        self.compute_type = compute_type

    def transcribe_pcm(
        self,
        pcm: np.ndarray,
        *,
        language: str = "zh",
        initial_offset: float = 0.0,
        initial_prompt: str = "",
    ) -> List[TranscriptSegment]:
        if pcm.size == 0:
            return []

        model = get_model(self.model_size, self.compute_type)
        segments, _info = model.transcribe(
            pcm,
            language=language,
            vad_filter=True,
            initial_prompt=initial_prompt or None,
            condition_on_previous_text=True,
            without_timestamps=False,
            beam_size=5,
        )

        result: List[TranscriptSegment] = []
        for segment in segments:
            text = (segment.text or "").strip()
            if not text:
                continue
            result.append(
                TranscriptSegment(
                    start=initial_offset + float(segment.start),
                    end=initial_offset + float(segment.end),
                    text=text,
                    is_partial=False,
                )
            )
        return result

    def transcribe_remote_chunk(
        self,
        media_url: str,
        *,
        start_time: float,
        duration: float,
        headers: dict[str, str] | None = None,
        language: str = "zh",
        initial_prompt: str = "",
    ) -> List[TranscriptSegment]:
        pcm = decode_remote_chunk_to_pcm(
          media_url,
          start_time=start_time,
          duration=duration,
          headers=headers,
        )
        return self.transcribe_pcm(
            pcm,
            language=language,
            initial_offset=start_time,
            initial_prompt=initial_prompt,
        )


class GroqASRClient(BaseASRClient):
    provider_name = "groq"

    def __init__(self, api_keys: list[str], model: str = "whisper-large-v3-turbo") -> None:
        if OpenAI is None or RateLimitError is None:
            raise ASRUnavailableError("openai is not installed. Install dependencies from requirements.txt first.")
        if not api_keys:
            raise ASRUnavailableError("No Groq API key provided. Set GROQ_API_KEY or GROQ_API_KEYS.")
        self.model = model
        self._clients = [OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1") for key in api_keys]
        self._cooldowns = [0.0 for _ in self._clients]
        self._lock = threading.Lock()

    def transcribe_remote_chunk(
        self,
        media_url: str,
        *,
        start_time: float,
        duration: float,
        headers: dict[str, str] | None = None,
        language: str = "zh",
        initial_prompt: str = "",
    ) -> List[TranscriptSegment]:
        audio_bytes = extract_remote_chunk_to_flac_bytes(
            media_url,
            start_time=start_time,
            duration=duration,
            headers=headers,
        )
        if not audio_bytes:
            return []

        while True:
            with self._lock:
                now = time.time()
                available = [index for index, cooldown in enumerate(self._cooldowns) if cooldown <= now]
                next_ready_at = min(self._cooldowns) if self._cooldowns else now

            if not available:
                time.sleep(max(1.0, next_ready_at - time.time()))
                continue

            for index in available:
                try:
                    audio_file = io.BytesIO(audio_bytes)
                    audio_file.name = f"chunk_{int(start_time * 1000)}.flac"
                    response = self._clients[index].audio.transcriptions.create(
                        file=audio_file,
                        model=self.model,
                        language=language,
                        prompt=initial_prompt or None,
                        temperature=0,
                        response_format="verbose_json",
                    )
                    payload = response.model_dump()
                    result: List[TranscriptSegment] = []
                    for segment in payload.get("segments", []):
                        text = str(segment.get("text", "")).strip()
                        if not text:
                            continue
                        result.append(
                            TranscriptSegment(
                                start=start_time + float(segment["start"]),
                                end=start_time + float(segment["end"]),
                                text=text,
                                is_partial=False,
                            )
                        )
                    return result
                except RateLimitError as error:
                    with self._lock:
                        self._cooldowns[index] = time.time() + parse_wait_seconds(str(error))
                    continue
                except Exception as error:
                    raise RuntimeError(f"Groq transcription failed: {error}") from error


def build_asr_client() -> BaseASRClient:
    groq_keys = collect_groq_api_keys()
    if groq_keys:
        return GroqASRClient(groq_keys)
    return FasterWhisperClient(model_size="small", compute_type="auto")
