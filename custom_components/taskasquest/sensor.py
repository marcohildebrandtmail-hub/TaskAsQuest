"""Sensor platform for Task as Quest."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import TaskAsQuestConfigEntry
from .const import DOMAIN
from .coordinator import TaskAsQuestCoordinator


@dataclass(frozen=True, kw_only=True)
class TaskAsQuestSensorDescription(SensorEntityDescription):
    """Describe a Task as Quest sensor."""

    value_key: str


SENSOR_DESCRIPTIONS = (
    TaskAsQuestSensorDescription(
        key="open_tasks",
        translation_key="open_tasks",
        icon="mdi:sword-cross",
        native_unit_of_measurement="quests",
        state_class=SensorStateClass.MEASUREMENT,
        value_key="open_task_count",
    ),
    TaskAsQuestSensorDescription(
        key="tasks_created",
        translation_key="tasks_created",
        icon="mdi:creation",
        native_unit_of_measurement="quests",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_key="tasks_created_total",
    ),
    TaskAsQuestSensorDescription(
        key="active_rules",
        translation_key="active_rules",
        icon="mdi:cog",
        native_unit_of_measurement="rules",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_key="rules_active",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TaskAsQuestConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Task as Quest sensors from a config entry."""
    async_add_entities(
        TaskAsQuestSensor(entry.runtime_data, entry, description)
        for description in SENSOR_DESCRIPTIONS
    )


class TaskAsQuestSensor(CoordinatorEntity[TaskAsQuestCoordinator], SensorEntity):
    """A coordinator-backed Task as Quest sensor."""

    _attr_has_entity_name = True
    entity_description: TaskAsQuestSensorDescription

    def __init__(
        self,
        coordinator: TaskAsQuestCoordinator,
        entry: TaskAsQuestConfigEntry,
        description: TaskAsQuestSensorDescription,
    ) -> None:
        """Initialize the sensor while preserving existing unique IDs."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._entry = entry

    @property
    def native_value(self) -> int:
        """Return the current in-memory coordinator value."""
        return int((self.coordinator.data or {}).get(self.entity_description.value_key, 0))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose the last created task on the creation counter."""
        if self.entity_description.key != "tasks_created":
            return None
        return {"last_task": self.coordinator.last_task_created}

    @property
    def device_info(self) -> DeviceInfo:
        """Group integration entities under the account service device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Task as Quest",
            manufacturer="Task as Quest",
            model="Cloud service",
            configuration_url=self.coordinator.client.base_url,
        )
