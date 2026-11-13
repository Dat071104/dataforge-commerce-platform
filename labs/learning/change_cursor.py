"""Tiny cursor comparison for the Week 5 change-sequence journal example."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable


@dataclass(frozen=True)
class JournalEvent:
    change_seq: int
    change_id: str
    source_updated_at: datetime
    business_key: str
    payload: str


def events_after_updated_at(
    events: Iterable[JournalEvent], cursor: datetime
) -> list[JournalEvent]:
    """Model the common strict timestamp-watermark query."""
    return sorted(
        (event for event in events if event.source_updated_at > cursor),
        key=lambda event: (event.source_updated_at, event.change_seq),
    )


def events_after_change_seq(
    events: Iterable[JournalEvent], cursor: int
) -> list[JournalEvent]:
    """Model a monotonic append-only journal sequence cursor."""
    return sorted(
        (event for event in events if event.change_seq > cursor),
        key=lambda event: event.change_seq,
    )
