"""Pure helpers for Task as Quest automation rules."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from .const import (
    CONDITIONS,
    DEFAULT_COOLDOWN,
    DIFFICULTIES,
    RULE_ASSIGNEES,
    RULE_CONDITION,
    RULE_COOLDOWN,
    RULE_DIFFICULTY,
    RULE_DUE_DATE_OFFSET,
    RULE_ENABLED,
    RULE_ENTITY_ID,
    RULE_ID,
    RULE_NOTIFY_APP,
    RULE_TASK_TITLE,
    RULE_TRIGGER_MODE,
    RULE_VALUE,
    TRIGGER_MODES,
)


def normalize_rule(
    rule: dict[str, Any],
    *,
    default_trigger_mode: str = "level",
) -> dict[str, Any]:
    """Return a validated, serializable rule while retaining compatibility."""
    normalized = dict(rule)
    normalized[RULE_ID] = str(rule.get(RULE_ID) or uuid4())
    normalized[RULE_ENTITY_ID] = str(rule.get(RULE_ENTITY_ID) or "").strip()
    condition = str(rule.get(RULE_CONDITION) or "equals")
    normalized[RULE_CONDITION] = condition if condition in CONDITIONS else "equals"
    normalized[RULE_VALUE] = str(rule.get(RULE_VALUE) or "")
    normalized[RULE_TASK_TITLE] = str(rule.get(RULE_TASK_TITLE) or "").strip()
    difficulty = str(rule.get(RULE_DIFFICULTY) or "medium")
    normalized[RULE_DIFFICULTY] = difficulty if difficulty in DIFFICULTIES else "medium"
    try:
        normalized[RULE_COOLDOWN] = max(0, int(rule.get(RULE_COOLDOWN, DEFAULT_COOLDOWN)))
    except (TypeError, ValueError):
        normalized[RULE_COOLDOWN] = DEFAULT_COOLDOWN
    normalized[RULE_ASSIGNEES] = [
        str(value) for value in rule.get(RULE_ASSIGNEES, []) if isinstance(value, str) and value
    ]
    try:
        due_date_offset = int(rule.get(RULE_DUE_DATE_OFFSET, -1))
    except (TypeError, ValueError):
        due_date_offset = -1
    normalized[RULE_DUE_DATE_OFFSET] = str(
        due_date_offset if due_date_offset == 100 or -1 <= due_date_offset <= 365 else -1
    )
    normalized[RULE_NOTIFY_APP] = bool(rule.get(RULE_NOTIFY_APP, True))
    normalized[RULE_ENABLED] = bool(rule.get(RULE_ENABLED, True))
    trigger_mode = str(rule.get(RULE_TRIGGER_MODE) or default_trigger_mode)
    normalized[RULE_TRIGGER_MODE] = (
        trigger_mode if trigger_mode in TRIGGER_MODES else default_trigger_mode
    )
    return normalized


def rule_signature(rule: dict[str, Any]) -> tuple[Any, ...]:
    """Return the functional identity used to detect exact duplicates."""
    return (
        rule.get(RULE_ENTITY_ID),
        rule.get(RULE_CONDITION),
        str(rule.get(RULE_VALUE)),
        rule.get(RULE_TASK_TITLE),
        rule.get(RULE_DIFFICULTY),
        int(rule.get(RULE_COOLDOWN, DEFAULT_COOLDOWN)),
        tuple(rule.get(RULE_ASSIGNEES, [])),
        str(rule.get(RULE_DUE_DATE_OFFSET, -1)),
        bool(rule.get(RULE_NOTIFY_APP, True)),
        bool(rule.get(RULE_ENABLED, True)),
        rule.get(RULE_TRIGGER_MODE),
    )


def rule_matches(rule: dict[str, Any], current_value: str | None) -> bool:
    """Return whether a Home Assistant state value matches a rule."""
    if current_value is None:
        return False
    condition = rule.get(RULE_CONDITION)
    expected = rule.get(RULE_VALUE)

    if condition in {"below", "above"}:
        try:
            current_number = float(current_value)
            expected_number = float(expected)
        except (TypeError, ValueError):
            return False
        return (
            current_number < expected_number
            if condition == "below"
            else current_number > expected_number
        )

    if condition == "equals":
        return str(current_value) == str(expected)
    if condition == "not_equals":
        return str(current_value) != str(expected)
    return False
