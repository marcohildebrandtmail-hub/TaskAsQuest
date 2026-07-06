"""Config flow for Task as Quest."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONDITIONS,
    CONF_APP_URL,
    CONF_LOGIN_NAME,
    CONF_PASSWORD,
    CONF_RECOVERY_CODE,
    CONF_RULES,
    CONF_TOTP_CODE,
    DEFAULT_APP_URL,
    DEFAULT_COOLDOWN,
    DIFFICULTIES,
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
from .app_client import TaskAsQuestClient


class TaskAsQuestConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a Task as Quest config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._login_data: dict[str, Any] = {}
        self._client: TaskAsQuestClient | None = None

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Create the integration entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._login_data = user_input
            
            client = TaskAsQuestClient(user_input[CONF_APP_URL])
            success, err_msg = await client.authenticate(
                user_input[CONF_LOGIN_NAME],
                user_input[CONF_PASSWORD],
            )
            
            if success:
                self._client = client
                if client.protection_version == 1:
                    return await self.async_step_recovery()
                else:
                    return await self._async_create_final_entry()
            elif err_msg == "totp_required":
                return await self.async_step_totp()
            else:
                errors["base"] = err_msg if err_msg else "auth_failed"
                await client.close()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_APP_URL, default=DEFAULT_APP_URL): str,
                    vol.Required(CONF_LOGIN_NAME): str,
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_totp(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle the TOTP step and authentication."""
        errors: dict[str, str] = {}

        if user_input is not None:
            totp_code = user_input.get(CONF_TOTP_CODE, "")
            self._login_data[CONF_TOTP_CODE] = totp_code
            
            client = TaskAsQuestClient(self._login_data[CONF_APP_URL])
            success, err_msg = await client.authenticate(
                self._login_data[CONF_LOGIN_NAME],
                self._login_data[CONF_PASSWORD],
                totp_code if totp_code else None,
            )

            if success:
                self._client = client
                if client.protection_version == 1:
                    return await self.async_step_recovery()
                else:
                    return await self._async_create_final_entry()
            else:
                errors["base"] = "auth_failed"
                await client.close()

        return self.async_show_form(
            step_id="totp",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TOTP_CODE): str,
                }
            ),
            errors=errors,
        )

    async def async_step_recovery(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle recovery code if crypto is enabled."""
        errors: dict[str, str] = {}

        if user_input is not None:
            recovery_code = user_input.get(CONF_RECOVERY_CODE, "")
            if not recovery_code:
                errors["base"] = "recovery_code_required"
            elif not self._client.unlock_protected_fields(recovery_code):
                errors["base"] = "recovery_code_invalid"
            else:
                self._login_data[CONF_RECOVERY_CODE] = recovery_code
                return await self._async_create_final_entry()

        return self.async_show_form(
            step_id="recovery",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_RECOVERY_CODE): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
        )

    async def _async_create_final_entry(self) -> config_entries.ConfigFlowResult:
        """Finalize the creation of the config entry."""
        await self.async_set_unique_id(self._client.user_id)
        self._abort_if_unique_id_configured()
        
        entry_data = dict(self._login_data)
        entry_data.pop(CONF_TOTP_CODE, None)
        
        user_id = self._client.user_id
        await self._client.close()
        
        return self.async_create_entry(
            title="Task as Quest",
            data={
                **entry_data,
                "user_id": user_id,
            },
            options={CONF_RULES: []},
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
        self._current_entity_id: str | None = None

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
        """Add one automation rule: Step 1 Entity Selection."""
        if user_input is not None:
            self._current_entity_id = user_input[RULE_ENTITY_ID]
            return await self.async_step_add_rule_details()

        return self.async_show_form(
            step_id="add_rule",
            data_schema=vol.Schema(
                {
                    vol.Required(RULE_ENTITY_ID): selector.EntitySelector(),
                }
            ),
        )

    async def _get_form_schema(self, entity_id: str, rule: dict[str, Any] | None = None) -> vol.Schema:
        """Get the schema for rule details."""
        if rule is None:
            rule = {}
            
        coordinator = self.hass.data[DOMAIN][self._config_entry.entry_id]
        companions = await coordinator.client.get_companions()
        
        assignee_options = [
            selector.SelectOptionDict(value=cid, label=name)
            for cid, name in companions.items()
        ]
        
        assignee_selector = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=assignee_options,
                multiple=True,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )
        
        due_date_options = [
            selector.SelectOptionDict(value="-1", label="Kein Datum"),
            selector.SelectOptionDict(value="0", label="Heute (23:59)"),
            selector.SelectOptionDict(value="1", label="Heute +1 Tag"),
            selector.SelectOptionDict(value="2", label="Heute +2 Tage"),
            selector.SelectOptionDict(value="3", label="Heute +3 Tage"),
            selector.SelectOptionDict(value="7", label="Heute +7 Tage"),
            selector.SelectOptionDict(value="100", label="Auto-Modus"),
        ]
        
        due_date_selector = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=due_date_options,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )
        
        schema = {
            vol.Required(RULE_CONDITION, default=rule.get(RULE_CONDITION, "equals")): vol.In(CONDITIONS),
        }
        
        if rule and RULE_VALUE in rule:
            schema[vol.Required(RULE_VALUE, default=rule[RULE_VALUE])] = selector.StateSelector(
                selector.StateSelectorConfig(entity_id=entity_id)
            )
        else:
            schema[vol.Required(RULE_VALUE)] = selector.StateSelector(
                selector.StateSelectorConfig(entity_id=entity_id)
            )
            
        if rule and RULE_TASK_TITLE in rule:
            schema[vol.Required(RULE_TASK_TITLE, default=rule[RULE_TASK_TITLE])] = str
        else:
            schema[vol.Required(RULE_TASK_TITLE)] = str
            
        schema.update({
            vol.Required(RULE_DIFFICULTY, default=rule.get(RULE_DIFFICULTY, "medium")): vol.In(DIFFICULTIES),
            vol.Required(RULE_COOLDOWN, default=rule.get(RULE_COOLDOWN, DEFAULT_COOLDOWN)): int,
            vol.Optional(RULE_ASSIGNEES, default=rule.get(RULE_ASSIGNEES, [])): assignee_selector,
            vol.Required(RULE_DUE_DATE_OFFSET, default=str(rule.get(RULE_DUE_DATE_OFFSET, "-1"))): due_date_selector,
            vol.Optional(RULE_NOTIFY_APP, default=rule.get(RULE_NOTIFY_APP, True)): bool,
        })
        
        if rule:
            schema[vol.Optional("delete_rule", default=False)] = bool
            
        return vol.Schema(schema)

    async def async_step_add_rule_details(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Add one automation rule: Step 2 Details."""
        if user_input is not None:
            rule = dict(user_input)
            rule[RULE_ENTITY_ID] = self._current_entity_id
            rule[RULE_ENABLED] = True
            self._rules.append(rule)
            return self.async_create_entry(
                title="",
                data={CONF_RULES: self._rules},
            )

        schema = await self._get_form_schema(self._current_entity_id)
        return self.async_show_form(
            step_id="add_rule_details",
            data_schema=schema,
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
        entity_id = rule.get(RULE_ENTITY_ID)

        if user_input is not None:
            if user_input.get("delete_rule"):
                self._rules.pop(self._selected_rule_index)
            else:
                updated_rule = dict(user_input)
                updated_rule.pop("delete_rule", None)
                updated_rule[RULE_ENTITY_ID] = entity_id
                updated_rule[RULE_ENABLED] = True
                self._rules[self._selected_rule_index] = updated_rule
            
            return self.async_create_entry(
                title="",
                data={CONF_RULES: self._rules},
            )

        schema = await self._get_form_schema(entity_id, rule)
        return self.async_show_form(
            step_id="edit_rule",
            data_schema=schema,
        )
