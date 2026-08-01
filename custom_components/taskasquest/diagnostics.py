"""Diagnostics support for Task as Quest."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import TaskAsQuestConfigEntry
from .const import (
    CONF_AUTH_TOKEN,
    CONF_LOGIN_NAME,
    CONF_PASSWORD,
    CONF_USER_ID,
    RULE_ASSIGNEES,
    RULE_TASK_TITLE,
    RULE_VALUE,
)

TO_REDACT = {
    CONF_AUTH_TOKEN,
    CONF_LOGIN_NAME,
    CONF_PASSWORD,
    CONF_USER_ID,
    RULE_ASSIGNEES,
    RULE_TASK_TITLE,
    RULE_VALUE,
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: TaskAsQuestConfigEntry,
) -> dict[str, Any]:
    """Return privacy-safe config entry diagnostics."""
    coordinator = entry.runtime_data
    data = coordinator.data or {}
    return {
        "config_entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "open_task_count": data.get("open_task_count", 0),
            "tasks_created_total": data.get("tasks_created_total", 0),
            "rules_active": data.get("rules_active", 0),
        },
    }
