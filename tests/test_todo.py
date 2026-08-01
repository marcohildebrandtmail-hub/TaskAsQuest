"""Tests for Task as Quest to-do value conversion."""

from datetime import UTC, date, datetime

from custom_components.taskasquest.todo import _parse_due, _serialize_due


def test_due_date_round_trip() -> None:
    """Date-only due values stay date-only."""
    due = date(2026, 7, 14)
    assert _serialize_due(due) == "2026-07-14"
    assert _parse_due({"due_date": "2026-07-14", "has_time": False}) == due


def test_due_datetime_is_serialized_as_utc() -> None:
    """Date-time due values are normalized to UTC for the provider."""
    due = datetime(2026, 7, 14, 23, 59, tzinfo=UTC)
    assert _serialize_due(due) == "2026-07-14T23:59:00Z"
