"""Config flow for Task as Quest."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    CONDITIONS,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_PB_URL,
    CONF_RULES,
    DEFAULT_COOLDOWN,
    DIFFICULTIES,
    DOMAIN,
    RULE_CONDITION,
    RULE_COOLDOWN,
    RULE_DIFFICULTY,
    RULE_ENABLED,
    RULE_ENTITY_ID,
    RULE_TASK_TITLE,
    RULE_VALUE,
)
from .pocketbase_client import PocketBaseClient


class TaskAsQuestConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a Task as Quest config flow."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Create the integration entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            client = PocketBaseClient(user_input[CONF_PB_URL])
            try:
                authenticated = await client.authenticate(
                    user_input[CONF_EMAIL],
                    user_input[CONF_PASSWORD],
                )
            finally:
                await client.close()

            if authenticated:
                await self.async_set_unique_id(user_input[CONF_EMAIL])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Task as Quest",
                    data=user_input,
                    options={CONF_RULES: []},
                )

            errors["base"] = "auth_failed"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PB_URL): str,
                    vol.Required(CONF_EMAIL): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> TaskAsQuestOptionsFlow:
        """Create the options flow."""
        return TaskAsQuestOptionsFlow(config_entry)


class TaskAsQuestOptionsFlow(config_entries.OptionsFlow):
    """Handle Task as Quest options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry
        self._rules = list(config_entry.options.get(CONF_RULES, []))

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Show the options menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["add_rule", "list_rules"],
        )

    async def async_step_add_rule(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Add one automation rule."""
        if user_input is not None:
            rule = dict(user_input)
            rule[RULE_ENABLED] = True
            self._rules.append(rule)
            return self.async_create_entry(
                title="",
                data={CONF_RULES: self._rules},
            )

        return self.async_show_form(
            step_id="add_rule",
            data_schema=vol.Schema(
                {
                    vol.Required(RULE_ENTITY_ID): str,
                    vol.Required(RULE_CONDITION, default="below"): vol.In(CONDITIONS),
                    vol.Required(RULE_VALUE): str,
                    vol.Required(RULE_TASK_TITLE): str,
                    vol.Required(RULE_DIFFICULTY, default="medium"): vol.In(DIFFICULTIES),
                    vol.Required(RULE_COOLDOWN, default=DEFAULT_COOLDOWN): int,
                }
            ),
            description_placeholders={
                "cooldown_hint": f"default: {DEFAULT_COOLDOWN} minutes"
            },
        )

    async def async_step_list_rules(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Delete an existing rule."""
        if user_input is not None:
            action = user_input.get("action", "")
            if action.startswith("delete_"):
                index = int(action.removeprefix("delete_"))
                if 0 <= index < len(self._rules):
                    self._rules.pop(index)
            return self.async_create_entry(
                title="",
                data={CONF_RULES: self._rules},
            )

        actions = {
            f"delete_{index}": f"Delete: {rule.get(RULE_TASK_TITLE, 'Rule')}"
            for index, rule in enumerate(self._rules)
        }
        if not actions:
            actions = {"none": "No rules configured"}

        return self.async_show_form(
            step_id="list_rules",
            data_schema=vol.Schema({vol.Required("action"): vol.In(actions)}),
        )
