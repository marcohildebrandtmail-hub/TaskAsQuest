"""Config flow for Task as Quest."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

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
        self._selected_rule_index: int | None = None

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Show the options menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["add_rule", "manage_rules"],
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
                    vol.Required(RULE_ENTITY_ID): selector.EntitySelector(),
                    vol.Required(RULE_CONDITION, default="below"): vol.In(CONDITIONS),
                    vol.Required(RULE_VALUE): str,
                    vol.Required(RULE_TASK_TITLE): str,
                    vol.Required(RULE_DIFFICULTY, default="medium"): vol.In(DIFFICULTIES),
                    vol.Required(RULE_COOLDOWN, default=DEFAULT_COOLDOWN): int,
                }
            ),
        )

    async def async_step_manage_rules(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """List and select a rule to edit or delete."""
        if user_input is not None:
            if user_input["rule_index"] == "none":
                return await self.async_step_init()
            
            self._selected_rule_index = int(user_input["rule_index"])
            return await self.async_step_edit_rule()

        options = {
            str(index): f"{rule.get(RULE_TASK_TITLE, 'Quest')} ({rule.get(RULE_ENTITY_ID)})"
            for index, rule in enumerate(self._rules)
        }
        if not options:
            options = {"none": "Keine Regeln konfiguriert"}

        return self.async_show_form(
            step_id="manage_rules",
            data_schema=vol.Schema(
                {
                    vol.Required("rule_index"): vol.In(options),
                }
            ),
        )

    async def async_step_edit_rule(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Edit or delete the selected rule."""
        if self._selected_rule_index is None:
            return await self.async_step_manage_rules()

        rule = self._rules[self._selected_rule_index]

        if user_input is not None:
            if user_input.get("delete_rule"):
                self._rules.pop(self._selected_rule_index)
            else:
                updated_rule = dict(user_input)
                updated_rule.pop("delete_rule", None)
                updated_rule[RULE_ENABLED] = True
                self._rules[self._selected_rule_index] = updated_rule
            
            return self.async_create_entry(
                title="",
                data={CONF_RULES: self._rules},
            )

        return self.async_show_form(
            step_id="edit_rule",
            data_schema=vol.Schema(
                {
                    vol.Required(RULE_ENTITY_ID, default=rule.get(RULE_ENTITY_ID)): selector.EntitySelector(),
                    vol.Required(RULE_CONDITION, default=rule.get(RULE_CONDITION, "below")): vol.In(CONDITIONS),
                    vol.Required(RULE_VALUE, default=rule.get(RULE_VALUE)): str,
                    vol.Required(RULE_TASK_TITLE, default=rule.get(RULE_TASK_TITLE)): str,
                    vol.Required(RULE_DIFFICULTY, default=rule.get(RULE_DIFFICULTY, "medium")): vol.In(DIFFICULTIES),
                    vol.Required(RULE_COOLDOWN, default=rule.get(RULE_COOLDOWN, DEFAULT_COOLDOWN)): int,
                    vol.Optional("delete_rule", default=False): bool,
                }
            ),
        )
