"""Tests for pure Task as Quest rule helpers."""

from custom_components.taskasquest.const import (
    RULE_CONDITION,
    RULE_COOLDOWN,
    RULE_DUE_DATE_OFFSET,
    RULE_ENTITY_ID,
    RULE_ID,
    RULE_TASK_TITLE,
    RULE_TRIGGER_MODE,
    RULE_VALUE,
)
from custom_components.taskasquest.rules import normalize_rule, rule_matches, rule_signature


def test_normalize_legacy_rule_preserves_level_behavior() -> None:
    """Legacy rules receive stable defaults without changing repeat semantics."""
    normalized = normalize_rule(
        {
            RULE_ENTITY_ID: "sensor.plant",
            RULE_CONDITION: "below",
            RULE_VALUE: 45,
            RULE_TASK_TITLE: "Water plant",
            RULE_COOLDOWN: "15",
            RULE_DUE_DATE_OFFSET: "not-a-number",
        }
    )

    assert normalized[RULE_ID]
    assert normalized[RULE_TRIGGER_MODE] == "level"
    assert normalized[RULE_VALUE] == "45"
    assert normalized[RULE_COOLDOWN] == 15
    assert normalized[RULE_DUE_DATE_OFFSET] == "-1"


def test_normalize_rule_clamps_invalid_values() -> None:
    """Invalid imported values cannot break the coordinator."""
    normalized = normalize_rule(
        {
            RULE_ENTITY_ID: "sensor.plant",
            RULE_CONDITION: "invalid",
            RULE_VALUE: "x",
            RULE_TASK_TITLE: "Quest",
            RULE_COOLDOWN: -10,
            RULE_DUE_DATE_OFFSET: 999,
        },
        default_trigger_mode="edge",
    )

    assert normalized[RULE_CONDITION] == "equals"
    assert normalized[RULE_COOLDOWN] == 0
    assert normalized[RULE_DUE_DATE_OFFSET] == "-1"
    assert normalized[RULE_TRIGGER_MODE] == "edge"


def test_rule_matches_numeric_and_text_conditions() -> None:
    """Every supported comparison behaves predictably."""
    assert rule_matches({RULE_CONDITION: "below", RULE_VALUE: "45"}, "44.9")
    assert rule_matches({RULE_CONDITION: "above", RULE_VALUE: "45"}, "46")
    assert rule_matches({RULE_CONDITION: "equals", RULE_VALUE: "on"}, "on")
    assert rule_matches({RULE_CONDITION: "not_equals", RULE_VALUE: "on"}, "off")
    assert not rule_matches({RULE_CONDITION: "below", RULE_VALUE: "45"}, "unknown")
    assert not rule_matches({RULE_CONDITION: "equals", RULE_VALUE: "on"}, None)


def test_rule_signature_ignores_generated_id() -> None:
    """Exact duplicate detection is independent of rule ids."""
    first = normalize_rule(
        {
            RULE_ENTITY_ID: "binary_sensor.door",
            RULE_CONDITION: "equals",
            RULE_VALUE: "on",
            RULE_TASK_TITLE: "Close door",
        }
    )
    second = {**first, RULE_ID: "different"}

    assert rule_signature(first) == rule_signature(second)
