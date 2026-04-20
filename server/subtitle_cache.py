from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from subtitle_buffer import SubtitleItem


logger = logging.getLogger("bilisub.cache")

MAX_CACHE_BYTES = 1_000_000_000
MAX_CACHE_AGE_DAYS = 30


class SubtitleCacheStore:
    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._prune_cache()

    def load(self, video_id: str) -> list[SubtitleItem]:
        path = self._path_for(video_id)
        if not path.exists():
            logger.info("cache miss for video_id=%s path=%s", video_id, path)
            return []

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

        items = payload.get("items", []) if isinstance(payload, dict) else []
        if not isinstance(items, list):
            return []

        result: list[SubtitleItem] = []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            text = str(raw.get("text", "")).strip()
            if not text:
                continue
            try:
                start = float(raw.get("start", 0.0))
                end = float(raw.get("end", 0.0))
            except (TypeError, ValueError):
                continue
            result.append(
                SubtitleItem(
                    id=str(raw.get("id", f"cached-{len(result)}")),
                    start=start,
                    end=end,
                    text=text,
                    is_partial=bool(raw.get("is_partial", False)),
                )
            )
        logger.info("cache load for video_id=%s items=%s path=%s", video_id, len(result), path)
        return result

    def save(
        self,
        video_id: str,
        page_url: str,
        items: list[SubtitleItem],
        *,
        source_url: str | None = None,
        status: str = "cached",
        note: str | None = None,
    ) -> None:
        path = self._path_for(video_id)
        payload = {
            "schema_version": 1,
            "video_id": video_id,
            "page_url": page_url,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "source_url": source_url,
            "status": status,
            "note": note,
            "buffered_until": items[-1].end if items else 0.0,
            "items": [item.to_dict() for item in items],
        }
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temp_path.replace(path)
        self._prune_cache()
        logger.info(
            "cache save for video_id=%s items=%s buffered_until=%.3f status=%s path=%s",
            video_id,
            len(items),
            payload["buffered_until"],
            status,
            path,
        )

    def _path_for(self, video_id: str) -> Path:
        safe = re.sub(r"[^a-zA-Z0-9._-]", "_", video_id)[:80] or "video"
        digest = hashlib.sha1(video_id.encode("utf-8")).hexdigest()[:12]
        return self.root_dir / f"{safe}__{digest}.json"

    def _prune_cache(self) -> None:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=MAX_CACHE_AGE_DAYS)

        files = [path for path in self.root_dir.glob("*.json") if path.is_file()]
        if not files:
            return

        kept_files: list[tuple[Path, float, datetime]] = []
        total_bytes = 0

        for path in files:
            try:
                stat = path.stat()
            except OSError:
                continue

            modified_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            if modified_at < cutoff:
                self._delete_cache_file(path, reason="expired")
                continue

            kept_files.append((path, stat.st_size, modified_at))
            total_bytes += stat.st_size

        if total_bytes <= MAX_CACHE_BYTES:
            return

        for path, size, _modified_at in sorted(kept_files, key=lambda item: item[2]):
            if total_bytes <= MAX_CACHE_BYTES:
                break
            self._delete_cache_file(path, reason="size-limit")
            total_bytes -= size

    def _delete_cache_file(self, path: Path, *, reason: str) -> None:
        try:
            path.unlink(missing_ok=True)
            logger.info("cache prune removed path=%s reason=%s", path, reason)
        except OSError as error:
            logger.warning("cache prune failed path=%s reason=%s error=%s", path, reason, error)
