from __future__ import annotations

from dataclasses import asdict, dataclass
from threading import Lock
from typing import List


@dataclass(slots=True)
class SubtitleItem:
    id: str
    start: float
    end: float
    text: str
    is_partial: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class SubtitleBuffer:
    def __init__(self) -> None:
        self._items: list[SubtitleItem] = []
        self._lock = Lock()

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def replace_items(self, items: list[SubtitleItem]) -> None:
        normalized = sorted(items, key=lambda item: (item.start, item.end, item.id))
        with self._lock:
            self._items = normalized

    def append_segments(self, segments: list[SubtitleItem], *, dedupe_margin: float = 0.25) -> None:
        with self._lock:
            if not segments:
                return

            merged = sorted([*self._items, *segments], key=lambda item: (item.start, item.end, item.id))
            deduped: list[SubtitleItem] = []
            for segment in merged:
                previous = deduped[-1] if deduped else None
                if previous and abs(segment.start - previous.start) <= dedupe_margin and abs(segment.end - previous.end) <= dedupe_margin and segment.text == previous.text:
                    continue
                deduped.append(segment)
            self._items = deduped

    def buffered_until(self) -> float:
        with self._lock:
            return self._items[-1].end if self._items else 0.0

    def buffered_until_from(self, current_time: float, *, margin: float = 1.0) -> float:
        with self._lock:
            if not self._items:
                return 0.0

            coverage_end = 0.0
            found_anchor = False
            for item in self._items:
                if not found_anchor:
                    if item.start - margin <= current_time <= item.end + margin:
                        coverage_end = max(current_time, item.end)
                        found_anchor = True
                        continue
                    if item.start > current_time:
                        # There is a gap before the next known subtitle.
                        return current_time
                    continue

                if item.start <= coverage_end + margin:
                    coverage_end = max(coverage_end, item.end)
                else:
                    break

            return coverage_end if found_anchor else current_time

    def query(self, current_time: float, *, window_before: float = 2.0, window_after: float = 30.0) -> list[SubtitleItem]:
        with self._lock:
            start_bound = max(0.0, current_time - window_before)
            end_bound = current_time + window_after
            return [
                item
                for item in self._items
                if item.end >= start_bound and item.start <= end_bound
            ]

    def has_coverage_at(self, target_time: float, *, margin: float = 1.0) -> bool:
        with self._lock:
            for item in self._items:
                if item.start - margin <= target_time <= item.end + margin:
                    return True
            return False

    def latest_end(self) -> float:
        with self._lock:
            return max((item.end for item in self._items), default=0.0)

    def recent_text(self, limit: int = 3) -> str:
        with self._lock:
            if not self._items:
                return ""
            return " ".join(item.text for item in self._items[-limit:] if item.text).strip()

    def snapshot(self) -> list[SubtitleItem]:
        with self._lock:
            return [
                SubtitleItem(
                    id=item.id,
                    start=item.start,
                    end=item.end,
                    text=item.text,
                    is_partial=item.is_partial,
                )
                for item in self._items
            ]
