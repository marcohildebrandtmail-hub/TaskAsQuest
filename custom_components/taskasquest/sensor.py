"""Sensor platform for Task as Quest."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TaskAsQuestCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors from config entry."""
    coordinator: TaskAsQuestCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            OpenTasksSensor(coordinator, entry),
            TasksCreatedSensor(coordinator, entry),
            ActiveRulesSensor(coordinator, entry),
        ]
    )


class OpenTasksSensor(CoordinatorEntity, SensorEntity):
    """Number of open tasks."""

    def __init__(self, coordinator: TaskAsQuestCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_open_tasks"
        self._attr_name = "Task as Quest — Offene Quests"
        self._attr_icon = "mdi:sword-cross"
        self._attr_native_unit_of_measurement = "Quests"

    @property
    def native_value(self) -> int:
        return self.coordinator.open_task_count


class TasksCreatedSensor(CoordinatorEntity, SensorEntity):
    """Total tasks created by automation."""

    def __init__(self, coordinator: TaskAsQuestCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_tasks_created"
        self._attr_name = "Task as Quest — Erstellte Quests"
        self._attr_icon = "mdi:creation"
        self._attr_native_unit_of_measurement = "Quests"

    @property
    def native_value(self) -> int:
        return self.coordinator.tasks_created_total

    @property
    def extra_state_attributes(self) -> dict:
        return {"last_task": self.coordinator.last_task_created}


class ActiveRulesSensor(CoordinatorEntity, SensorEntity):
    """Number of active rules."""

    def __init__(self, coordinator: TaskAsQuestCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_active_rules"
        self._attr_name = "Task as Quest — Aktive Regeln"
        self._attr_icon = "mdi:cog"
        self._attr_native_unit_of_measurement = "Regeln"

    @property
    def native_value(self) -> int:
        data = self.coordinator.data or {}
        return data.get("rules_active", 0)
