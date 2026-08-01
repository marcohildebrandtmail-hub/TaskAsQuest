"""Tests for coordinator rule processing."""

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.taskasquest.const import (
    CONF_APP_URL,
    CONF_PASSWORD,
    DOMAIN,
    RULE_CONDITION,
    RULE_COOLDOWN,
    RULE_DUE_DATE_OFFSET,
    RULE_ENTITY_ID,
    RULE_TASK_TITLE,
    RULE_VALUE,
)
from custom_components.taskasquest.coordinator import TaskAsQuestCoordinator
from custom_components.taskasquest.rules import normalize_rule


async def test_rule_creation_reuses_open_task_snapshot(hass: HomeAssistant) -> None:
    """A second matching rule pass does not make or search for a duplicate."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_APP_URL: "https://example.test", CONF_PASSWORD: "password"},
    )
    entry.add_to_hass(hass)
    client = MagicMock()
    client.create_task = AsyncMock(return_value={"id": "task-1", "title": "Water plant"})
    rule = normalize_rule(
        {
            RULE_ENTITY_ID: "sensor.plant",
            RULE_CONDITION: "below",
            RULE_VALUE: "45",
            RULE_TASK_TITLE: "Water plant",
            RULE_COOLDOWN: 0,
            RULE_DUE_DATE_OFFSET: "-1",
        }
    )
    coordinator = TaskAsQuestCoordinator(hass, entry, client, [rule])
    open_tasks: list[dict] = []

    with patch.object(coordinator._store, "async_save", AsyncMock()):
        assert await coordinator._async_evaluate_rules([rule], open_tasks) == 1
        assert await coordinator._async_evaluate_rules([rule], open_tasks) == 0

    client.create_task.assert_awaited_once()
    assert open_tasks == [{"id": "task-1", "title": "Water plant"}]
    assert coordinator.tasks_created_total == 1
