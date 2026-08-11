"""The in-app Task as Quest control centre."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from .const import (
    CONF_LOGIN_NAME,
    CONF_RULES,
    DOMAIN,
    RULE_ENABLED,
    RULE_ENTITY_ID,
    RULE_ID,
    RULE_TASK_TITLE,
)
from .rules import normalize_rule


class TaskAsQuestDashboardView(HomeAssistantView):
    """Expose the safe, non-secret data needed by the control centre."""

    url = "/api/taskasquest/dashboard"
    name = "api:taskasquest:dashboard"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the view."""
        self.hass = hass

    @staticmethod
    def _require_admin(request: web.Request) -> None:
        user = request["hass_user"]
        if not user.is_admin:
            raise web.HTTPForbidden(reason="Administrator rights are required")

    def _entry(self, entry_id: str) -> Any:
        entry = self.hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            raise web.HTTPNotFound(reason="Task as Quest account not found")
        return entry

    async def get(self, request: web.Request) -> web.Response:
        """Return entries, configured rules and the current quest snapshot."""
        self._require_admin(request)
        entries: list[dict[str, Any]] = []
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            coordinator = entry.runtime_data if entry.state is ConfigEntryState.LOADED else None
            data = coordinator.data if coordinator else {}
            companions = {}
            if coordinator and hasattr(coordinator, "client"):
                import contextlib
                with contextlib.suppress(Exception):
                    companions = await coordinator.client.get_companions()
            entries.append(
                {
                    "entry_id": entry.entry_id,
                    "title": entry.title or entry.data.get(CONF_LOGIN_NAME, "Task as Quest"),
                    "loaded": entry.state is ConfigEntryState.LOADED,
                    "rules": list(entry.options.get(CONF_RULES, [])),
                    "open_tasks": list((data or {}).get("open_tasks", [])),
                    "open_task_count": int((data or {}).get("open_task_count", 0)),
                    "tasks_created_total": int((data or {}).get("tasks_created_total", 0)),
                    "companions": companions,
                }
            )
        return web.json_response({"entries": entries})

    async def post(self, request: web.Request) -> web.Response:
        """Create, update, toggle or remove a rule without exposing credentials."""
        self._require_admin(request)
        payload = await request.json()
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(reason="Expected a JSON object")
        entry = self._entry(str(payload.get("entry_id", "")))
        action = payload.get("action")
        rules = list(entry.options.get(CONF_RULES, []))

        if action == "toggle":
            rule_id = str(payload.get(RULE_ID, ""))
            enabled = bool(payload.get(RULE_ENABLED))
            for rule in rules:
                if rule.get(RULE_ID) == rule_id:
                    rule[RULE_ENABLED] = enabled
                    break
            else:
                raise web.HTTPNotFound(reason="Rule not found")
        elif action == "delete":
            rule_id = str(payload.get(RULE_ID, ""))
            updated = [rule for rule in rules if rule.get(RULE_ID) != rule_id]
            if len(updated) == len(rules):
                raise web.HTTPNotFound(reason="Rule not found")
            rules = updated
        elif action in {"create", "update"}:
            raw_rule = payload.get("rule")
            if not isinstance(raw_rule, dict):
                raise web.HTTPBadRequest(reason="Rule is missing")
            rule = normalize_rule(raw_rule, default_trigger_mode="edge")
            if not rule[RULE_ENTITY_ID] or not rule[RULE_TASK_TITLE]:
                raise web.HTTPBadRequest(reason="Entity and quest title are required")
            if action == "create":
                rules.append(rule)
            else:
                for index, existing in enumerate(rules):
                    if existing.get(RULE_ID) == rule[RULE_ID]:
                        rules[index] = rule
                        break
                else:
                    raise web.HTTPNotFound(reason="Rule not found")
        else:
            raise web.HTTPBadRequest(reason="Unknown action")

        self.hass.config_entries.async_update_entry(
            entry,
            options={**entry.options, CONF_RULES: rules},
        )
        return web.json_response({"ok": True})


async def async_register_dashboard(hass: HomeAssistant) -> None:
    """Register the one global panel and its API endpoints."""
    from homeassistant.components import frontend
    from homeassistant.components.http import StaticPathConfig

    if (
        hass.data.get(f"{DOMAIN}_dashboard_registered")
        or "frontend" not in hass.config.components
    ):
        return
    hass.data[f"{DOMAIN}_dashboard_registered"] = True
    static_dir = Path(__file__).parent / "frontend"
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                f"/{DOMAIN}/taskasquest-panel.js",
                str(static_dir / "taskasquest-panel.js"),
                False,
            )
        ]
    )
    hass.http.register_view(TaskAsQuestDashboardView(hass))
    frontend.async_register_built_in_panel(
        hass,
        "custom",
        sidebar_title="Task as Quest",
        sidebar_icon="mdi:sword-cross",
        frontend_url_path=DOMAIN,
        config={
            "_panel_custom": {
                "name": "taskasquest-panel",
                "module_url": f"/{DOMAIN}/taskasquest-panel.js?v=3.2.0",
                "embed_iframe": False,
            }
        },
        require_admin=True,
    )
