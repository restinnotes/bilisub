from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class AudioSource:
    url: str
    type: str = "direct"
    headers: dict[str, str] = field(default_factory=dict)
    backup_urls: list[str] = field(default_factory=list)
    meta: dict[str, object] = field(default_factory=dict)


def choose_media_url(source: AudioSource) -> str:
    if source.url:
        return source.url
    for url in source.backup_urls:
        if url:
            return url
    raise ValueError("No usable media URL available in audio source payload")


def iter_media_urls(source: AudioSource) -> list[str]:
    candidates: list[str] = []
    if source.url:
        candidates.append(source.url)
    candidates.extend(url for url in source.backup_urls if url)
    if not candidates:
        raise ValueError("No usable media URL available in audio source payload")
    return candidates
