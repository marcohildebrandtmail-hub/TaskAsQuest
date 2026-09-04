"""Tests for coordinator rule processing."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.taskasquest.const import (
    CONF_APP_URL,
    CONF_PASSWORD,
    DOMAIN,
    MASS_OUTAGE_RULE_ID,
    MASS_OUTAGE_TASK_TITLE,
    RULE_CONDITION,
    RULE_COOLDOWN,
    RULE_DUE_DATE_OFFSET,
    RULE_ENTITY_ID,
    RULE_TASK_TITLE,
    RULE_TRIGGER_MODE,
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


async def test_level_rule_waits_for_startup_grace_before_creating_quest(
    hass: HomeAssistant,
) -> None:
    """Only settled unavailable states can create a quest after startup."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_APP_URL: "https://example.test", CONF_PASSWORD: "password"},
    )
    entry.add_to_hass(hass)
    client = MagicMock()
    client.token = "token"
    client.user_id = "user"
    client.refresh_auth = AsyncMock()
    client.get_open_tasks = AsyncMock(return_value=[])
    client.create_task = AsyncMock(return_value={"id": "task-1", "title": "Check sensor"})
    rule = normalize_rule(
        {
            RULE_ENTITY_ID: "binary_sensor.kitchen_contact",
            RULE_CONDITION: "equals",
            RULE_VALUE: "unavailable",
            RULE_TASK_TITLE: "Check sensor",
            RULE_COOLDOWN: 0,
            RULE_DUE_DATE_OFFSET: "-1",
            RULE_TRIGGER_MODE: "level",
        }
    )
    hass.states.async_set("binary_sensor.kitchen_contact", "unavailable")
    coordinator = TaskAsQuestCoordinator(hass, entry, client, [rule])

    with patch.object(coordinator._store, "async_save", AsyncMock()):
        initial = await coordinator._async_update_data()
        assert initial["tasks_created_this_update"] == 0
        client.create_task.assert_not_awaited()

        coordinator._rules_armed = True
        settled = await coordinator._async_update_data()
        
    assert settled["tasks_created_this_update"] == 0
    client.create_task.assert_not_awaited()

    # Fast forward past the burst protection window
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=35))
    await hass.async_block_till_done()

    client.create_task.assert_awaited_once()


async def test_burst_of_rules_creates_one_consolidated_mass_outage(
    hass: HomeAssistant,
) -> None:
    """Several simultaneous matches create one quest instead of a flood."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_APP_URL: "https://example.test", CONF_PASSWORD: "password"},
    )
    entry.add_to_hass(hass)
    client = MagicMock()
    client.create_task = AsyncMock(
        side_effect=lambda title, **_kwargs: {"id": title, "title": title}
    )
    rules = [
        normalize_rule(
            {
                RULE_ENTITY_ID: f"binary_sensor.test_{index}",
                RULE_CONDITION: "equals",
                RULE_VALUE: "on",
                RULE_TASK_TITLE: f"Check sensor {index}",
                RULE_COOLDOWN: 0,
                RULE_DUE_DATE_OFFSET: "-1",
            }
        )
        for index in range(4)
    ]
    coordinator = TaskAsQuestCoordinator(hass, entry, client, rules)
    coordinator._rules_armed = True

    with patch.object(coordinator._store, "async_save", AsyncMock()):
        coordinator._async_queue_rules(rules)
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=35))
        await hass.async_block_till_done()

    client.create_task.assert_awaited_once()
    args = client.create_task.await_args
    assert args.args[0] == MASS_OUTAGE_TASK_TITLE
    assert "4 Regeln" in args.kwargs["description"]
    assert "keine einzelnen Gerätequests" in args.kwargs["description"]


async def test_mass_outage_is_not_recreated_while_quest_is_open(
    hass: HomeAssistant,
) -> None:
    """A continuing infrastructure outage does not create recurring quests."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_APP_URL: "https://example.test", CONF_PASSWORD: "password"},
    )
    entry.add_to_hass(hass)
    client = MagicMock()
    client.create_task = AsyncMock(
        return_value={"id": "mass-outage", "title": MASS_OUTAGE_TASK_TITLE}
    )
    rules = [
        normalize_rule(
            {
                RULE_ENTITY_ID: f"sensor.zigbee_{index}_last_seen",
                RULE_CONDITION: "equals",
                RULE_VALUE: "unavailable",
                RULE_TASK_TITLE: f"Zigbee device {index} unavailable",
                RULE_COOLDOWN: 0,
                RULE_DUE_DATE_OFFSET: "-1",
            }
        )
        for index in range(4)
    ]
    coordinator = TaskAsQuestCoordinator(hass, entry, client, rules)
    open_tasks: list[dict] = []

    with patch.object(coordinator._store, "async_save", AsyncMock()):
        assert await coordinator._async_create_mass_outage(rules, open_tasks) == 1
        assert await coordinator._async_create_mass_outage(rules, open_tasks) == 0
        open_tasks.clear()
        assert await coordinator._async_create_mass_outage(rules, open_tasks) == 0

    client.create_task.assert_awaited_once()


async def test_mass_outage_cooldown_is_restored_after_restart(
    hass: HomeAssistant,
) -> None:
    """The persisted outage cooldown survives an integration restart."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_APP_URL: "https://example.test", CONF_PASSWORD: "password"},
    )
    entry.add_to_hass(hass)
    coordinator = TaskAsQuestCoordinator(hass, entry, MagicMock(), [])

    with patch.object(
        coordinator._store,
        "async_load",
        AsyncMock(
            return_value={
                "last_created_by_rule": {MASS_OUTAGE_RULE_ID: 12345.0},
            }
        ),
    ):
        await coordinator._async_setup()

    assert coordinator._last_created_by_rule[MASS_OUTAGE_RULE_ID] == 12345.0
