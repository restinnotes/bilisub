from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict

from asr_client import ASRUnavailableError, build_asr_client
from audio_utils import AudioDecodeError
from media_fetcher import AudioSource, iter_media_urls
from subtitle_cache import SubtitleCacheStore
from subtitle_buffer import SubtitleBuffer, SubtitleItem


logger = logging.getLogger("bilisub.session")


def compute_target_lead(playback_rate: float) -> float:
    return min(20.0, max(10.0, playback_rate * 6.0))


@dataclass(slots=True)
class SessionState:
    session_id: str
    page_url: str
    video_id: str
    playback_rate: float = 1.0
    current_time: float = 0.0
    current_epoch: int = 0
    status: str = "idle"
    status_detail: str = "Waiting for audio source"
    last_error: str | None = None
    audio_source: AudioSource | None = None
    subtitle_buffer: SubtitleBuffer = field(default_factory=SubtitleBuffer)
    worker_thread: threading.Thread | None = None
    worker_stop: threading.Event = field(default_factory=threading.Event)
    worker_kick: threading.Event = field(default_factory=threading.Event)
    cursor_time: float = 0.0
    chunk_seconds: float = 14.0
    chunk_overlap: float = 4.0
    exhausted: bool = False


class SessionManager:
    def __init__(self) -> None:
        self._sessions: Dict[str, SessionState] = {}
        self._lock = threading.Lock()
        self._asr = build_asr_client()
        self._cache_store = SubtitleCacheStore(Path(__file__).resolve().parent / "cache" / "subtitles")
        self._video_locks: dict[str, threading.Lock] = {}

    def start_session(self, page_url: str, video_id: str) -> SessionState:
        session = SessionState(
            session_id=uuid.uuid4().hex,
            page_url=page_url,
            video_id=video_id,
        )
        cached_items = self._cache_store.load(video_id)
        if cached_items:
            session.subtitle_buffer.replace_items(cached_items)
            session.cursor_time = session.subtitle_buffer.buffered_until()
            session.status = "ready"
            session.status_detail = f"Loaded cached subtitles through {session.cursor_time:.1f}s"
        else:
            self._persist_video_cache(session, status="initialized", note="session created before first subtitle segment")
        logger.info(
            "session start video_id=%s session_id=%s cached_items=%s buffered_until=%.3f provider=%s",
            video_id,
            session.session_id,
            len(cached_items),
            session.subtitle_buffer.buffered_until(),
            self._asr.provider_name,
        )
        with self._lock:
            self._sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str) -> SessionState:
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"Unknown session_id: {session_id}")
        return session

    def load_source(self, session_id: str, source: AudioSource) -> SessionState:
        session = self.get_session(session_id)
        session.audio_source = source
        session.status = "loading-source"
        session.status_detail = f"Audio source ready, building subtitle buffer with {self._asr.provider_name}"
        session.last_error = None
        session.exhausted = False
        logger.info(
            "source load video_id=%s session_id=%s type=%s url=%s backups=%s provider=%s",
            session.video_id,
            session.session_id,
            source.type,
            source.url,
            len(source.backup_urls),
            self._asr.provider_name,
        )
        self._persist_video_cache(session, status="source-loaded", note="audio source accepted")
        session.worker_kick.set()
        self._ensure_worker(session)
        return session

    def update_play(self, session_id: str, current_time: float) -> SessionState:
        session = self.get_session(session_id)
        session.current_time = current_time
        session.status = "playing"
        session.status_detail = "Playback active, keeping subtitle buffer warm"
        session.worker_kick.set()
        return session

    def update_pause(self, session_id: str, current_time: float) -> SessionState:
        session = self.get_session(session_id)
        session.current_time = current_time
        session.status = "paused"
        session.status_detail = "Playback paused at current subtitle position"
        session.worker_kick.set()
        return session

    def update_seek(self, session_id: str, target_time: float) -> SessionState:
        session = self.get_session(session_id)
        session.current_time = target_time
        session.current_epoch += 1
        has_cached_coverage = session.subtitle_buffer.has_coverage_at(target_time)
        session.cursor_time = (
            target_time
            if not has_cached_coverage
            else max(target_time, session.subtitle_buffer.buffered_until_from(target_time))
        )
        session.exhausted = False
        session.status = "seeking"
        session.status_detail = (
            f"Seeked to {target_time:.1f}s and reusing cached subtitles"
            if has_cached_coverage
            else f"Seeked to {target_time:.1f}s and rebuilding subtitle buffer from there"
        )
        session.last_error = None
        session.worker_stop.clear()
        logger.info(
            "seek video_id=%s session_id=%s target=%.3f has_cached_coverage=%s next_cursor=%.3f",
            session.video_id,
            session.session_id,
            target_time,
            has_cached_coverage,
            session.cursor_time,
        )
        session.worker_kick.set()
        self._ensure_worker(session)
        return session

    def update_rate(self, session_id: str, playback_rate: float) -> SessionState:
        session = self.get_session(session_id)
        session.playback_rate = playback_rate
        session.status_detail = f"Playback rate {playback_rate:.2f}x, target lead {compute_target_lead(playback_rate):.1f}s"
        session.worker_kick.set()
        return session

    def update_status_clock(self, session_id: str, current_time: float) -> SessionState:
        session = self.get_session(session_id)
        session.current_time = current_time
        return session

    def end_session(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is None:
            return
        session.worker_stop.set()
        session.worker_kick.set()
        if session.worker_thread and session.worker_thread.is_alive():
            session.worker_thread.join(timeout=1.5)

    def _ensure_worker(self, session: SessionState) -> None:
        if session.worker_thread and session.worker_thread.is_alive():
            return

        session.worker_stop.clear()
        session.worker_kick.clear()
        session.worker_thread = threading.Thread(
            target=self._worker_loop,
            name=f"bilisub-worker-{session.session_id[:8]}",
            args=(session,),
            daemon=True,
        )
        session.worker_thread.start()

    def _worker_loop(self, session: SessionState) -> None:
        while not session.worker_stop.is_set():
            if session.audio_source is None:
                session.worker_kick.wait(timeout=0.5)
                session.worker_kick.clear()
                continue

            target_lead = compute_target_lead(session.playback_rate)
            buffered_until = session.subtitle_buffer.buffered_until_from(session.current_time)
            lead = buffered_until - session.current_time

            if session.exhausted or lead >= target_lead:
                session.status = "ready" if lead >= target_lead else session.status
                session.status_detail = f"Current lead {max(0.0, lead):.1f}s, target {target_lead:.1f}s"
                session.worker_kick.wait(timeout=0.75)
                session.worker_kick.clear()
                continue

            expected_epoch = session.current_epoch
            start_time = session.cursor_time
            session.status = "buffering"
            session.status_detail = f"Transcribing {start_time:.1f}s to {start_time + session.chunk_seconds:.1f}s"
            logger.info(
                "buffer attempt video_id=%s session_id=%s epoch=%s start=%.3f chunk=%.3f lead=%.3f provider=%s",
                session.video_id,
                session.session_id,
                expected_epoch,
                start_time,
                session.chunk_seconds,
                lead,
                self._asr.provider_name,
            )

            try:
                segments = None
                errors: list[str] = []
                prompt_text = session.subtitle_buffer.recent_text(limit=3)
                for source_url in iter_media_urls(session.audio_source):
                    try:
                        logger.info(
                            "asr try video_id=%s session_id=%s provider=%s url=%s start=%.3f duration=%.3f",
                            session.video_id,
                            session.session_id,
                            self._asr.provider_name,
                            source_url,
                            start_time,
                            session.chunk_seconds,
                        )
                        segments = self._asr.transcribe_remote_chunk(
                            source_url,
                            start_time=start_time,
                            duration=session.chunk_seconds,
                            headers=session.audio_source.headers,
                            initial_prompt=prompt_text,
                        )
                        logger.info(
                            "asr ok video_id=%s session_id=%s provider=%s url=%s segments=%s",
                            session.video_id,
                            session.session_id,
                            self._asr.provider_name,
                            source_url,
                            len(segments),
                        )
                        break
                    except (AudioDecodeError, RuntimeError) as error:
                        logger.warning(
                            "asr failed video_id=%s session_id=%s provider=%s url=%s error=%s",
                            session.video_id,
                            session.session_id,
                            self._asr.provider_name,
                            source_url,
                            error,
                        )
                        errors.append(str(error))

                if segments is None:
                    raise AudioDecodeError(" | ".join(errors))
                if expected_epoch != session.current_epoch:
                    continue

                subtitle_items = [
                    SubtitleItem(
                        id=f"{expected_epoch}-{index}-{int(segment.start * 1000)}",
                        start=segment.start,
                        end=segment.end,
                        text=segment.text,
                        is_partial=segment.is_partial,
                    )
                    for index, segment in enumerate(segments)
                ]
                if expected_epoch != session.current_epoch:
                    continue

                session.subtitle_buffer.append_segments(subtitle_items)
                logger.info(
                    "transcribe ok video_id=%s session_id=%s segments=%s buffered_until=%.3f",
                    session.video_id,
                    session.session_id,
                    len(subtitle_items),
                    session.subtitle_buffer.buffered_until_from(session.current_time),
                )
                self._persist_video_cache(session, status="cached", note=f"segments={len(subtitle_items)}")
                session.cursor_time = start_time + max(1.0, session.chunk_seconds - session.chunk_overlap)
                session.last_error = None

                if not subtitle_items:
                    session.exhausted = True
                    session.status_detail = "No new subtitle segments were returned; media may be exhausted"
                    self._persist_video_cache(session, status="empty-result", note="decode succeeded but ASR returned no segments")
            except (AudioDecodeError, ASRUnavailableError, ValueError, RuntimeError) as error:
                session.last_error = str(error)
                session.status = "error"
                session.status_detail = f"Subtitle pipeline failed. Check ffmpeg and {self._asr.provider_name} dependencies."
                logger.error(
                    "worker error video_id=%s session_id=%s error=%s",
                    session.video_id,
                    session.session_id,
                    error,
                )
                self._persist_video_cache(session, status="error", note=str(error))
                session.worker_kick.wait(timeout=1.5)
                session.worker_kick.clear()

    def to_status_payload(self, session: SessionState) -> dict[str, object]:
        buffered_until = session.subtitle_buffer.buffered_until_from(session.current_time)
        return {
            "session_id": session.session_id,
            "current_epoch": session.current_epoch,
            "buffered_until": buffered_until,
            "status": session.status,
            "status_detail": session.status_detail,
            "last_error": session.last_error,
            "target_lead": compute_target_lead(session.playback_rate),
            "current_time": session.current_time,
            "playback_rate": session.playback_rate,
            "asr_provider": self._asr.provider_name,
        }

    def _persist_video_cache(self, session: SessionState, *, status: str = "cached", note: str | None = None) -> None:
        lock = self._video_locks.setdefault(session.video_id, threading.Lock())
        snapshot = session.subtitle_buffer.snapshot()
        source_url = session.audio_source.url if session.audio_source else None
        with lock:
            self._cache_store.save(
                session.video_id,
                session.page_url,
                snapshot,
                source_url=source_url,
                status=status,
                note=note,
            )
