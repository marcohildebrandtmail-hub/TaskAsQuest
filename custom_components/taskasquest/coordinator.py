"""Data coordinator and event-driven rule engine for Task as Quest."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .app_client import TaskAsQuestClient
from .const import (
    CONF_AUTH_TOKEN,
    CONF_USER_ID,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    RULE_ASSIGNEES,
    RULE_COOLDOWN,
    RULE_DIFFICULTY,
    RULE_DUE_DATE_OFFSET,
    RULE_ENABLED,
    RULE_ENTITY_ID,
    RULE_ID,
    RULE_NOTIFY_APP,
    RULE_TASK_TITLE,
    RULE_TRIGGER_MODE,
    STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
)
from .exceptions import (
    TaskAsQuestAuthenticationError,
    TaskAsQuestCannotConnectError,
    TaskAsQuestError,
    TaskAsQuestRateLimitError,
)
from .rules import rule_matches

_LOGGER = logging.getLogger(__name__)


class TaskAsQuestCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinate cloud data and Home Assistant entity rules."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: TaskAsQuestClient,
        rules: list[dict[str, Any]],
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=DEFAULT_UPDATE_INTERVAL,
        )
        self.config_entry = entry
        self.client = client
        self.rules = rules
        self.open_task_count = 0
        self.tasks_created_total = 0
        self.last_task_created: str | None = None
        self._last_created_by_rule: dict[str, float] = {}
        self._rule_unsubscribe: Callable[[], None] | None = None
        self._rule_lock = asyncio.Lock()
        self._store: Store[dict[str, Any]] = Store(
            hass,
            STORAGE_VERSION,
            f"{STORAGE_KEY_PREFIX}.{entry.entry_id}",
        )

    async def _async_setup(self) -> None:
        """Restore persistent counters and cooldown timestamps."""
        stored = await self._store.async_load() or {}
        self.tasks_created_total = max(0, int(stored.get("tasks_created_total", 0)))
        last_task = stored.get("last_task_created")
        self.last_task_created = last_task if isinstance(last_task, str) else None
        cooldowns = stored.get("last_created_by_rule", {})
        if isinstance(cooldowns, dict):
            active_rule_ids = {rule[RULE_ID] for rule in self.rules}
            self._last_created_by_rule = {
                str(rule_id): float(timestamp)
                for rule_id, timestamp in cooldowns.items()
                if rule_id in active_rule_ids and isinstance(timestamp, (int, float))
            }

    @callback
    def async_start(self) -> None:
        """Subscribe to entity changes after setup completed."""
        self._subscribe_to_rule_entities()

    @callback
    def async_shutdown(self) -> None:
        """Remove rule event subscriptions."""
        if self._rule_unsubscribe:
            self._rule_unsubscribe()
            self._rule_unsubscribe = None

    @callback
    def update_rules(self, rules: list[dict[str, Any]]) -> None:
        """Replace automation rules and update state subscriptions."""
        self.rules = rules
        self._subscribe_to_rule_entities()

    @callback
    def async_publish_rule_update(self) -> None:
        """Publish changed rule counts without performing network I/O."""
        self.async_set_updated_data(
            self._coordinator_data(
                list((self.data or {}).get("open_tasks", [])),
                0,
            )
        )

    @callback
    def _subscribe_to_rule_entities(self) -> None:
        if self._rule_unsubscribe:
            self._rule_unsubscribe()
            self._rule_unsubscribe = None
        entity_ids = {
            rule[RULE_ENTITY_ID]
            for rule in self.rules
            if rule.get(RULE_ENABLED, True) and rule.get(RULE_ENTITY_ID)
        }
        if entity_ids:
            self._rule_unsubscribe = async_track_state_change_event(
                self.hass,
                entity_ids,
                self._handle_state_change,
            )

    @callback
    def _handle_state_change(self, event: Event) -> None:
        """Schedule rule processing without blocking the event bus."""
        self.config_entry.async_create_background_task(
            self.hass,
            self._async_handle_state_change(event),
            f"{DOMAIN} rule evaluation",
        )

    async def _async_handle_state_change(self, event: Event) -> None:
        entity_id = event.data.get("entity_id")
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        if not entity_id or new_state is None:
            return

        matching_rules: list[dict[str, Any]] = []
        for rule in self.rules:
            if (
                not rule.get(RULE_ENABLED, True)
                or rule.get(RULE_ENTITY_ID) != entity_id
                or not rule_matches(rule, new_state.state)
            ):
                continue
            if rule.get(RULE_TRIGGER_MODE, "level") == "edge" and rule_matches(
                rule,
                old_state.state if old_state else None,
            ):
                continue
            matching_rules.append(rule)

        if not matching_rules:
            return
        try:
            tasks = list((self.data or {}).get("open_tasks", []))
            created = await self._async_evaluate_rules(matching_rules, tasks)
            if created:
                self.open_task_count = len(tasks)
                self.async_set_updated_data(self._coordinator_data(tasks, created))
        except TaskAsQuestAuthenticationError:
            self.config_entry.async_start_reauth(self.hass)
        except TaskAsQuestError as err:
            _LOGGER.warning("Task as Quest rule evaluation failed: %s", err)

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch cloud data and process repeating level rules."""
        try:
            old_token = self.client.token
            await self.client.refresh_auth()
            if self.client.token != old_token:
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data={
                        **self.config_entry.data,
                        CONF_AUTH_TOKEN: self.client.token,
                        CONF_USER_ID: self.client.user_id,
                    },
                )

            open_tasks = await self.client.get_open_tasks()
            level_rules = [
                rule
                for rule in self.rules
                if rule.get(RULE_ENABLED, True)
                and rule.get(RULE_TRIGGER_MODE, "level") == "level"
                and (state := self.hass.states.get(rule.get(RULE_ENTITY_ID, ""))) is not None
                and rule_matches(rule, state.state)
            ]
            created = await self._async_evaluate_rules(level_rules, open_tasks)
            self.open_task_count = len(open_tasks)
            return self._coordinator_data(open_tasks, created)
        except TaskAsQuestAuthenticationError as err:
            raise ConfigEntryAuthFailed("Task as Quest authentication expired") from err
        except TaskAsQuestRateLimitError as err:
            raise UpdateFailed(
                "Task as Quest rate limit reached",
                retry_after=err.retry_after,
            ) from err
        except TaskAsQuestCannotConnectError as err:
            raise UpdateFailed("Could not connect to Task as Quest") from err
        except TaskAsQuestError as err:
            raise UpdateFailed(f"Task as Quest update failed: {err}") from err

    def _coordinator_data(
        self,
        open_tasks: list[dict[str, Any]],
        created: int,
    ) -> dict[str, Any]:
        return {
            "open_tasks": open_tasks,
            "open_task_count": len(open_tasks),
            "tasks_created_total": self.tasks_created_total,
            "last_task_created": self.last_task_created,
            "rules_active": sum(1 for rule in self.rules if rule.get(RULE_ENABLED, True)),
            "tasks_created_this_update": created,
        }

    async def _async_evaluate_rules(
        self,
        rules: list[dict[str, Any]],
        open_tasks: list[dict[str, Any]],
    ) -> int:
        """Create tasks for matching rules using one shared open-task snapshot."""
        created = 0
        async with self._rule_lock:
            open_titles = {
                task.get("title") for task in open_tasks if isinstance(task.get("title"), str)
            }
            now = time.time()
            for rule in rules:
                entity_id = rule.get(RULE_ENTITY_ID)
                task_title = rule.get(RULE_TASK_TITLE)
                rule_id = rule.get(RULE_ID)
                if not entity_id or not task_title or not rule_id:
                    continue

                cooldown = max(0, int(rule.get(RULE_COOLDOWN, 0))) * 60
                last_created = self._last_created_by_rule.get(rule_id, 0)
                if cooldown and now - last_created < cooldown:
                    continue
                if task_title in open_titles:
                    continue

                task = await self.client.create_task(
                    task_title,
                    difficulty=rule.get(RULE_DIFFICULTY, "medium"),
                    description=f"Created by Home Assistant rule for {entity_id}.",
                    due_date=self._due_date(rule),
                    assignees=rule.get(RULE_ASSIGNEES, []),
                    notify_app=rule.get(RULE_NOTIFY_APP, True),
                )
                open_tasks.append(task)
                open_titles.add(task_title)
                created += 1
                self.tasks_created_total += 1
                self.last_task_created = task_title
                self._last_created_by_rule[rule_id] = now

            if created:
                await self._async_save_state()
        return created

    @staticmethod
    def _due_date(rule: dict[str, Any]) -> str | None:
        try:
            offset = int(rule.get(RULE_DUE_DATE_OFFSET, -1))
        except (TypeError, ValueError):
            return None
        if offset < 0:
            return None
        current_time = dt_util.now()
        add_days = 0 if offset == 100 and current_time.hour < 18 else offset
        if offset == 100 and current_time.hour >= 18:
            add_days = 1
        target_date = current_time + timedelta(days=add_days)
        target_utc = target_date.replace(
            hour=23,
            minute=59,
            second=59,
            microsecond=0,
        ).astimezone(dt_util.UTC)
        return target_utc.isoformat().replace("+00:00", "Z")

    async def _async_save_state(self) -> None:
        await self._store.async_save(
            {
                "tasks_created_total": self.tasks_created_total,
                "last_task_created": self.last_task_created,
                "last_created_by_rule": self._last_created_by_rule,
            }
        )

    @staticmethod
    def _rule_matches(rule: dict[str, Any], current_value: str) -> bool:
        """Backward-compatible wrapper around the pure rule matcher."""
        return rule_matches(rule, current_value)
