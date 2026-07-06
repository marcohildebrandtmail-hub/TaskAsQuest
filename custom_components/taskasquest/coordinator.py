"""Data coordinator for Task as Quest."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    RULE_CONDITION,
    RULE_COOLDOWN,
    RULE_DIFFICULTY,
    RULE_ENABLED,
    RULE_ENTITY_ID,
    RULE_ASSIGNEES,
    RULE_DUE_DATE_OFFSET,
    RULE_NOTIFY_APP,
    RULE_TASK_TITLE,
    RULE_VALUE,
)
from homeassistant.util import dt as dt_util
from .app_client import TaskAsQuestClient

_LOGGER = logging.getLogger(__name__)


class TaskAsQuestCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinate Task as Quest updates and automation rules."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: TaskAsQuestClient,
        rules: list[dict[str, Any]] | None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.config_entry = entry
        self.client = client
        self.rules = rules or []
        self.open_task_count = 0
        self.tasks_created_total = 0
        self.last_task_created: str | None = None
        self._last_created_by_rule: dict[str, float] = {}

    def update_rules(self, rules: list[dict[str, Any]] | None) -> None:
        """Replace automation rules from options."""
        self.rules = rules or []

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch current data and evaluate automation rules."""
        try:
            open_tasks = await self.client.get_open_tasks()
            self.open_task_count = len(open_tasks)
            created = await self._async_evaluate_rules()
            return {
                "open_tasks": open_tasks,
                "open_task_count": self.open_task_count,
                "tasks_created_total": self.tasks_created_total,
                "last_task_created": self.last_task_created,
                "rules_active": sum(1 for rule in self.rules if rule.get(RULE_ENABLED, True)),
                "tasks_created_this_update": created,
            }
        except Exception as err:  # noqa: BLE001 - HA coordinators should surface UpdateFailed.
            raise UpdateFailed(f"Task as Quest update failed: {err}") from err

    async def _async_evaluate_rules(self) -> int:
        """Evaluate enabled HA entity rules and create matching quests."""
        created = 0
        now = self.hass.loop.time()

        for index, rule in enumerate(self.rules):
            if not rule.get(RULE_ENABLED, True):
                continue

            entity_id = rule.get(RULE_ENTITY_ID)
            task_title = rule.get(RULE_TASK_TITLE)
            if not entity_id or not task_title:
                continue

            state = self.hass.states.get(entity_id)
            if state is None:
                continue

            if not self._rule_matches(rule, state.state):
                continue

            cooldown = float(rule.get(RULE_COOLDOWN, 0) or 0) * 60
            rule_key = f"{index}:{entity_id}:{task_title}"
            last_created = self._last_created_by_rule.get(rule_key, 0)
            if cooldown and now - last_created < cooldown:
                continue

            existing = await self.client.find_task_by_title(task_title)
            if existing:
                self._last_created_by_rule[rule_key] = now
                continue

            due_date = None
            offset = int(rule.get(RULE_DUE_DATE_OFFSET, -1))
            if offset >= 0 or offset == 100:
                current_time = dt_util.now()
                if offset == 100:
                    add_days = 0 if current_time.hour < 18 else 1
                else:
                    add_days = offset
                
                target_date = current_time + timedelta(days=add_days)
                target_utc = target_date.replace(hour=23, minute=59, second=59, microsecond=0).astimezone(dt_util.UTC)
                due_date = target_utc.isoformat().replace("+00:00", "Z")

            task = await self.client.create_task(
                task_title,
                difficulty=rule.get(RULE_DIFFICULTY, "medium"),
                description=f"Created by Home Assistant rule for {entity_id}.",
                due_date=due_date,
                assignees=rule.get(RULE_ASSIGNEES, []),
                notify_app=rule.get(RULE_NOTIFY_APP, True),
            )
            if task:
                created += 1
                self.tasks_created_total += 1
                self.last_task_created = task_title
                self._last_created_by_rule[rule_key] = now

        return created

    @staticmethod
    def _rule_matches(rule: dict[str, Any], current_value: str) -> bool:
        """Return whether a Home Assistant state matches a rule."""
        condition = rule.get(RULE_CONDITION)
        expected = rule.get(RULE_VALUE)

        if condition in {"below", "above"}:
            try:
                current_number = float(current_value)
                expected_number = float(expected)
            except (TypeError, ValueError):
                return False

            if condition == "below":
                return current_number < expected_number
            return current_number > expected_number

        current_text = str(current_value)
        expected_text = str(expected)
        if condition == "equals":
            return current_text == expected_text
        if condition == "not_equals":
            return current_text != expected_text
        return False
