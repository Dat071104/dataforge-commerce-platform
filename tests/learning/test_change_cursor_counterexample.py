from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from labs.learning.change_cursor import (
    JournalEvent,
    events_after_change_seq,
    events_after_updated_at,
)

ROOT = Path(__file__).parents[2]


def test_same_timestamp_late_event_is_missed_by_updated_at_but_seen_by_sequence() -> None:
    timestamp = datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)
    first_seen = JournalEvent(101, "chg-101", timestamp, "order-1", "status=created")
    late_arrival = JournalEvent(102, "chg-102", timestamp, "order-2", "status=paid")

    # The first poll consumed sequence 101 and stored its timestamp as cursor.
    timestamp_cursor = first_seen.source_updated_at
    sequence_cursor = first_seen.change_seq

    # A second event arrives later but has the same source timestamp. The
    # strict `updated_at > cursor` query cannot distinguish it from data seen
    # in the previous poll; the change journal can.
    assert events_after_updated_at([late_arrival], timestamp_cursor) == []
    assert events_after_change_seq([late_arrival], sequence_cursor) == [late_arrival]


def test_week5_publisher_uses_change_seq_as_the_version_order() -> None:
    publisher = ROOT / "cloud" / "sql_bigquery" / "week5" / "publish.sql"
    text = publisher.read_text(encoding="utf-8")
    assert "ORDER BY change_seq DESC" in text
    assert "source.change_seq > target.effective_seq" in text
