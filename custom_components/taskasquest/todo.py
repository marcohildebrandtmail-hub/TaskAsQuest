"""To-do platform for Task as Quest."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import TaskAsQuestConfigEntry
from .const import DOMAIN
from .coordinator import TaskAsQuestCoordinator
from .exceptions import TaskAsQuestError


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TaskAsQuestConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Task as Quest to-do platform."""
    async_add_entities([TaskAsQuestTodoList(entry.runtime_data, entry)])


def _parse_due(task: dict[str, Any]) -> date | datetime | None:
    """Convert the provider due date to a Home Assistant to-do due value."""
    value = task.get("due_date")
    if not isinstance(value, str) or not value:
        return None
    if task.get("has_time") or "T" in value:
        return dt_util.parse_datetime(value)
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _serialize_due(value: date | datetime | None) -> str | None:
    """Convert a Home Assistant due value to the provider representation."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        return dt_util.as_utc(value).isoformat().replace("+00:00", "Z")
    return value.isoformat()


class TaskAsQuestTodoList(CoordinatorEntity[TaskAsQuestCoordinator], TodoListEntity):
    """Represent open Task as Quest quests as a native to-do list."""

    _attr_has_entity_name = True
    _attr_translation_key = "quests"
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
        | TodoListEntityFeature.SET_DUE_DATE_ON_ITEM
        | TodoListEntityFeature.SET_DUE_DATETIME_ON_ITEM
    )

    def __init__(
        self,
        coordinator: TaskAsQuestCoordinator,
        entry: TaskAsQuestConfigEntry,
    ) -> None:
        """Initialize the to-do list."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_quests"
        self._entry = entry

    @property
    def todo_items(self) -> list[TodoItem] | None:
        """Return open quests from coordinator memory only."""
        if not self.coordinator.data:
            return None
        return [
            TodoItem(
                uid=str(task["id"]),
                summary=str(task.get("title") or "Quest"),
                status=TodoItemStatus.NEEDS_ACTION,
                description=task.get("description"),
                due=_parse_due(task),
            )
            for task in self.coordinator.data.get("open_tasks", [])
            if task.get("id")
        ]

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Create a new quest from Home Assistant."""
        if not item.summary:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="quest_title_required",
            )
        try:
            await self.coordinator.client.create_task(
                title=item.summary,
                description=item.description,
                due_date=_serialize_due(item.due),
            )
            await self.coordinator.async_request_refresh()
        except TaskAsQuestError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="create_quest_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Update quest title, description, due date and status."""
        if not item.uid or not item.summary or item.status is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="quest_fields_required",
            )
        current_record = next(
            (
                task
                for task in (self.coordinator.data or {}).get("open_tasks", [])
                if task.get("id") == item.uid
            ),
            None,
        )
        status = "completed" if item.status is TodoItemStatus.COMPLETED else "open"
        try:
            await self.coordinator.client.update_task(
                item.uid,
                title=item.summary,
                description=item.description,
                status=status,
                due_date=_serialize_due(item.due),
                current_record=current_record,
            )
            await self.coordinator.async_request_refresh()
        except TaskAsQuestError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="update_quest_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Delete one or more quests and surface partial failures."""
        try:
            for uid in uids:
                await self.coordinator.client.delete_task(uid)
            await self.coordinator.async_request_refresh()
        except TaskAsQuestError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="delete_quests_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    @property
    def device_info(self) -> DeviceInfo:
        """Group the to-do list with the account sensors."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Task as Quest",
            manufacturer="Task as Quest",
            model="Cloud service",
            configuration_url=self.coordinator.client.base_url,
        )
