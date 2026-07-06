"""Todo platform for Task as Quest."""

from __future__ import annotations

from typing import Any

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
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
    """Set up todo platform from config entry."""
    coordinator: TaskAsQuestCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([TaskAsQuestTodoList(coordinator, entry)])


class TaskAsQuestTodoList(CoordinatorEntity[TaskAsQuestCoordinator], TodoListEntity):
    """A todo list for Task as Quest quests."""

    _attr_has_entity_name = True
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
    )

    def __init__(self, coordinator: TaskAsQuestCoordinator, entry: ConfigEntry) -> None:
        """Initialize the todo list."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_quests"
        self._attr_name = "Quests"

    @property
    def todo_items(self) -> list[TodoItem] | None:
        """Return the list of todo items."""
        if not self.coordinator.data or "open_tasks" not in self.coordinator.data:
            return None

        return [
            TodoItem(
                uid=task["id"],
                summary=task["title"],
                status=TodoItemStatus.NEEDS_ACTION,
                description=task.get("description"),
            )
            for task in self.coordinator.data["open_tasks"]
        ]

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Create a new quest."""
        await self.coordinator.client.create_task(
            title=item.summary,
            description=item.description,
        )
        await self.coordinator.async_refresh()

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Update a quest (mark as completed)."""
        if item.status == TodoItemStatus.COMPLETED:
            success = await self.coordinator.client.update_task_status(item.uid, "completed")
            if success:
                await self.coordinator.async_refresh()

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Delete quests."""
        for uid in uids:
            await self.coordinator.client.delete_task(uid)
        await self.coordinator.async_refresh()
