from __future__ import annotations

import shutil
import subprocess
from typing import Iterable

import numpy as np


class AudioDecodeError(RuntimeError):
    pass


def ensure_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise AudioDecodeError("ffmpeg is required and was not found in PATH.")


def decode_remote_chunk_to_pcm(
    media_url: str,
    *,
    start_time: float,
    duration: float,
    headers: dict[str, str] | None = None,
    sample_rate: int = 16000,
) -> np.ndarray:
    ensure_ffmpeg()
    safe_headers = dict(headers or {})
    user_agent = safe_headers.pop("User-Agent", None)
    command = [
        "ffmpeg",
        "-v",
        "error",
    ]

    if user_agent:
        command.extend(["-user_agent", user_agent])

    command.extend([
        "-ss",
        f"{start_time}",
        "-t",
        f"{duration}",
    ])

    if safe_headers:
        header_blob = "".join(f"{key}: {value}\r\n" for key, value in safe_headers.items())
        command.extend(["-headers", header_blob])

    command.extend(
        [
            "-i",
            media_url,
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-f",
            "s16le",
            "pipe:1",
        ]
    )

    completed = subprocess.run(command, capture_output=True, check=False)
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="ignore")
        raise AudioDecodeError(f"ffmpeg failed while decoding remote media: {stderr.strip()}")

    pcm_int16 = np.frombuffer(completed.stdout, dtype=np.int16)
    return pcm_int16.astype(np.float32) / 32768.0


def extract_remote_chunk_to_flac_bytes(
    media_url: str,
    *,
    start_time: float,
    duration: float,
    headers: dict[str, str] | None = None,
    sample_rate: int = 16000,
) -> bytes:
    ensure_ffmpeg()
    safe_headers = dict(headers or {})
    user_agent = safe_headers.pop("User-Agent", None)
    command = ["ffmpeg", "-v", "error"]

    if user_agent:
        command.extend(["-user_agent", user_agent])

    command.extend(["-ss", f"{start_time}", "-t", f"{duration}"])

    if safe_headers:
        header_blob = "".join(f"{key}: {value}\r\n" for key, value in safe_headers.items())
        command.extend(["-headers", header_blob])

    command.extend(
        [
            "-i",
            media_url,
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-c:a",
            "flac",
            "-f",
            "flac",
            "pipe:1",
        ]
    )

    completed = subprocess.run(command, capture_output=True, check=False)
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="ignore")
        raise AudioDecodeError(f"ffmpeg failed while extracting remote media: {stderr.strip()}")
    return completed.stdout
