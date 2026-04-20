from __future__ import annotations

import importlib
from typing import Any

from pydantic import BaseModel, Field

from media_fetcher import AudioSource
from session_manager import SessionManager


fastapi = importlib.import_module("fastapi")
fastapi_cors = importlib.import_module("fastapi.middleware.cors")
FastAPI = fastapi.FastAPI
HTTPException = fastapi.HTTPException
Query = fastapi.Query
CORSMiddleware = fastapi_cors.CORSMiddleware


session_manager = SessionManager()


class StartSessionRequest(BaseModel):
    page_url: str
    video_id: str


class LoadSourcePayload(BaseModel):
    url: str
    type: str = "direct"
    headers: dict[str, str] = Field(default_factory=dict)
    backup_urls: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


class LoadSourceRequest(BaseModel):
    session_id: str
    audio_source: LoadSourcePayload


class CurrentTimeRequest(BaseModel):
    session_id: str
    current_time: float


class SeekRequest(BaseModel):
    session_id: str
    target_time: float


class RateRequest(BaseModel):
    session_id: str
    playback_rate: float


class EndSessionRequest(BaseModel):
    session_id: str


app = FastAPI(title="BiliSub Local Server", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, object]:
    return {"ok": True, "service": "bilisub-local-server"}


@app.post("/session/start")
def start_session(request: StartSessionRequest) -> dict[str, object]:
    session = session_manager.start_session(request.page_url, request.video_id)
    return session_manager.to_status_payload(session)


@app.post("/session/load-source")
def load_source(request: LoadSourceRequest) -> dict[str, object]:
    try:
        session = session_manager.load_source(
            request.session_id,
            AudioSource(
                url=request.audio_source.url,
                type=request.audio_source.type,
                headers=request.audio_source.headers,
                backup_urls=request.audio_source.backup_urls,
                meta=request.audio_source.meta,
            ),
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return session_manager.to_status_payload(session)


@app.post("/session/play")
def play(request: CurrentTimeRequest) -> dict[str, object]:
    try:
        session = session_manager.update_play(request.session_id, request.current_time)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return session_manager.to_status_payload(session)


@app.post("/session/pause")
def pause(request: CurrentTimeRequest) -> dict[str, object]:
    try:
        session = session_manager.update_pause(request.session_id, request.current_time)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return session_manager.to_status_payload(session)


@app.post("/session/seek")
def seek(request: SeekRequest) -> dict[str, object]:
    try:
        session = session_manager.update_seek(request.session_id, request.target_time)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return session_manager.to_status_payload(session)


@app.post("/session/rate")
def rate(request: RateRequest) -> dict[str, object]:
    try:
        session = session_manager.update_rate(request.session_id, request.playback_rate)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return session_manager.to_status_payload(session)


@app.get("/session/status")
def session_status(session_id: str = Query(...), current_time: float = Query(0.0)) -> dict[str, object]:
    try:
        session = session_manager.update_status_clock(session_id, current_time)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return session_manager.to_status_payload(session)


@app.get("/subtitles")
def subtitles(
    session_id: str = Query(...),
    current_time: float = Query(0.0),
    window_before: float = Query(2.0),
    window_after: float = Query(30.0),
) -> dict[str, object]:
    try:
        session = session_manager.update_status_clock(session_id, current_time)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    items = [
        item.to_dict()
        for item in session.subtitle_buffer.query(
            current_time,
            window_before=window_before,
            window_after=window_after,
        )
    ]
    return {
        **session_manager.to_status_payload(session),
        "items": items,
    }


@app.post("/session/end")
def end_session(request: EndSessionRequest) -> dict[str, object]:
    session_manager.end_session(request.session_id)
    return {"ok": True}
