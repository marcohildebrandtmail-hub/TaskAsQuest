"""Config and options flows for Task as Quest."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from yarl import URL

from .app_client import TaskAsQuestClient
from .const import (
    CONDITIONS,
    CONF_APP_URL,
    CONF_AUTH_TOKEN,
    CONF_LOGIN_NAME,
    CONF_PASSWORD,
    CONF_RULES,
    CONF_TOTP_CODE,
    CONF_USER_ID,
    DEFAULT_APP_URL,
    DEFAULT_COOLDOWN,
    DIFFICULTIES,
    DOMAIN,
    RULE_ASSIGNEES,
    RULE_CONDITION,
    RULE_COOLDOWN,
    RULE_DIFFICULTY,
    RULE_DUE_DATE_OFFSET,
    RULE_ENABLED,
    RULE_ENTITY_ID,
    RULE_ID,
    RULE_NOTIFY_APP,
    RULE_TASK_TITLE,
    RULE_TRIGGER_MODE,
    RULE_VALUE,
    TRIGGER_MODES,
)
from .exceptions import (
    TaskAsQuestAuthenticationError,
    TaskAsQuestCannotConnectError,
    TaskAsQuestEncryptionError,
    TaskAsQuestError,
    TaskAsQuestRateLimitError,
    TaskAsQuestTotpRequiredError,
)
from .rules import normalize_rule


def _normalize_url(value: str) -> str:
    """Validate and normalize an HTTP(S) server URL."""
    try:
        url = URL(value.strip())
    except (TypeError, ValueError) as err:
        raise vol.Invalid("invalid_url") from err
    if url.scheme not in {"http", "https"} or not url.host:
        raise vol.Invalid("invalid_url")
    return str(url).rstrip("/")


class TaskAsQuestConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a Task as Quest config flow."""

    VERSION = 2

    def __init__(self) -> None:
        """Initialize flow state."""
        self._login_data: dict[str, Any] = {}
        self._client: TaskAsQuestClient | None = None
        self._target_entry: config_entries.ConfigEntry | None = None

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Create a new integration entry."""
        if user_input is not None:
            try:
                user_input[CONF_APP_URL] = _normalize_url(user_input[CONF_APP_URL])
            except vol.Invalid:
                self._errors = {"base": "invalid_url"}
            else:
                self._login_data = user_input
                result = await self._async_attempt_login()
                if result is not None:
                    return result
        return self.async_show_form(
            step_id="user",
            data_schema=self._login_schema(include_url=True),
            errors=getattr(self, "_errors", {}),
        )

    async def async_step_reauth(
        self,
        entry_data: dict[str, Any],
    ) -> config_entries.ConfigFlowResult:
        """Start reauthentication."""
        self._target_entry = self._get_reauth_entry()
        self._login_data = {
            CONF_APP_URL: entry_data.get(CONF_APP_URL, DEFAULT_APP_URL),
            CONF_LOGIN_NAME: entry_data.get(CONF_LOGIN_NAME, ""),
        }
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Collect current credentials for reauthentication."""
        if user_input is not None:
            self._login_data.update(user_input)
            result = await self._async_attempt_login()
            if result is not None:
                return result
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self._login_schema(include_url=False),
            errors=getattr(self, "_errors", {}),
        )

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Allow changing server and account credentials."""
        if self._target_entry is None:
            self._target_entry = self._get_reconfigure_entry()
            self._login_data = {
                CONF_APP_URL: self._target_entry.data.get(
                    CONF_APP_URL,
                    DEFAULT_APP_URL,
                ),
                CONF_LOGIN_NAME: self._target_entry.data.get(CONF_LOGIN_NAME, ""),
            }
        if user_input is not None:
            try:
                user_input[CONF_APP_URL] = _normalize_url(user_input[CONF_APP_URL])
            except vol.Invalid:
                self._errors = {"base": "invalid_url"}
            else:
                self._login_data.update(user_input)
                result = await self._async_attempt_login()
                if result is not None:
                    return result
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self._login_schema(include_url=True),
            errors=getattr(self, "_errors", {}),
        )

    def _login_schema(self, *, include_url: bool) -> vol.Schema:
        schema: dict[Any, Any] = {}
        if include_url:
            schema[
                vol.Required(
                    CONF_APP_URL,
                    default=self._login_data.get(CONF_APP_URL, DEFAULT_APP_URL),
                )
            ] = selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
            )
        schema[
            vol.Required(
                CONF_LOGIN_NAME,
                default=self._login_data.get(CONF_LOGIN_NAME, ""),
            )
        ] = str
        schema[vol.Required(CONF_PASSWORD)] = selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        )
        return vol.Schema(schema)

    async def _async_attempt_login(
        self,
        totp_code: str | None = None,
    ) -> config_entries.ConfigFlowResult | None:
        """Authenticate and map provider failures to translated flow errors."""
        self._errors = {}
        client = TaskAsQuestClient(
            self._login_data[CONF_APP_URL],
            async_get_clientsession(self.hass),
            self.hass.async_add_executor_job,
        )
        try:
            await client.authenticate(
                self._login_data[CONF_LOGIN_NAME],
                self._login_data[CONF_PASSWORD],
                totp_code,
            )
            await client.async_unlock_protected_fields(self._login_data[CONF_PASSWORD])
        except TaskAsQuestTotpRequiredError:
            if totp_code:
                self._errors["base"] = "invalid_totp"
                return None
            return await self.async_step_totp()
        except TaskAsQuestAuthenticationError:
            self._errors["base"] = "auth_failed"
            return None
        except TaskAsQuestEncryptionError:
            self._errors["base"] = "encryption_unlock_failed"
            return None
        except (TaskAsQuestCannotConnectError, TaskAsQuestRateLimitError):
            self._errors["base"] = "cannot_connect"
            return None
        except TaskAsQuestError:
            self._errors["base"] = "unknown"
            return None
        self._client = client
        return await self._async_finish_login()

    async def async_step_totp(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Collect and validate the required TOTP code."""
        if user_input is not None:
            result = await self._async_attempt_login(user_input[CONF_TOTP_CODE])
            if result is not None:
                return result
        return self.async_show_form(
            step_id="totp",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TOTP_CODE): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                            autocomplete="one-time-code",
                        )
                    )
                }
            ),
            errors=getattr(self, "_errors", {}),
        )

    async def _async_finish_login(self) -> config_entries.ConfigFlowResult:
        """Create or update a config entry after successful authentication."""
        if self._client is None or self._client.user_id is None:
            return self.async_abort(reason="unknown")
        await self.async_set_unique_id(self._client.user_id)
        if self._target_entry is None:
            self._abort_if_unique_id_configured()
        else:
            self._abort_if_unique_id_mismatch()

        entry_data = {
            **self._login_data,
            CONF_AUTH_TOKEN: self._client.token,
            CONF_USER_ID: self._client.user_id,
        }
        entry_data.pop(CONF_TOTP_CODE, None)
        entry_data.pop("recovery_code", None)

        if self._target_entry is not None:
            return self.async_update_reload_and_abort(
                self._target_entry,
                data={**self._target_entry.data, **entry_data},
                unique_id=self._client.user_id,
            )
        return self.async_create_entry(
            title=self._login_data[CONF_LOGIN_NAME],
            data=entry_data,
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
    """Manage Task as Quest automation rules."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry
        self._rules = [
            normalize_rule(rule, default_trigger_mode="level")
            for rule in config_entry.options.get(CONF_RULES, [])
        ]
        self._selected_rule_index: int | None = None
        self._current_entity_id: str | None = None
        self._form_error: dict[str, str] = {}

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
        """Select the entity for a new rule."""
        if user_input is not None:
            raw_entity = user_input[RULE_ENTITY_ID]
            if isinstance(raw_entity, list):
                self._current_entity_id = ", ".join(raw_entity[:3])
            else:
                self._current_entity_id = str(raw_entity)
            return await self.async_step_add_rule_details()
        return self.async_show_form(
            step_id="add_rule",
            data_schema=vol.Schema(
                {
                    vol.Required(RULE_ENTITY_ID): selector.EntitySelector(
                        selector.EntitySelectorConfig(multiple=True)
                    )
                }
            ),
        )

    async def _get_form_schema(
        self,
        entity_id: str,
        rule: dict[str, Any] | None = None,
    ) -> vol.Schema:
        """Build the details form and retain removed companion selections."""
        rule = rule or {}
        companions: dict[str, str] = {}
        self._form_error = {}
        try:
            coordinator = self._config_entry.runtime_data
            if coordinator and hasattr(coordinator, "client"):
                companions = await coordinator.client.get_companions()
        except (AttributeError, TaskAsQuestError, Exception):
            pass

        selected_assignees = rule.get(RULE_ASSIGNEES, [])
        for companion_id in selected_assignees:
            companions.setdefault(companion_id, companion_id)
        assignee_options = [
            selector.SelectOptionDict(value=companion_id, label=name)
            for companion_id, name in sorted(companions.items(), key=lambda item: item[1])
        ]

        due_date_options = [
            selector.SelectOptionDict(value="-1", label="Keine Fälligkeit / No due date"),
            selector.SelectOptionDict(value="0", label="Heute (23:59) / Today"),
            selector.SelectOptionDict(value="1", label="Morgen (23:59) / Tomorrow"),
            selector.SelectOptionDict(value="2", label="In 2 Tagen / In 2 days"),
            selector.SelectOptionDict(value="3", label="In 3 Tagen / In 3 days"),
            selector.SelectOptionDict(value="7", label="In 7 Tagen / In 7 days"),
            selector.SelectOptionDict(value="100", label="Auto (Heute / ab 18:00 Uhr Morgen)"),
        ]

        first_entity = entity_id.split(",")[0].strip() if entity_id else None
        value_selector = (
            selector.StateSelector(selector.StateSelectorConfig(entity_id=first_entity))
            if first_entity and "," not in entity_id
            else selector.TextSelector()
        )

        schema: dict[Any, Any] = {
            vol.Required(
                RULE_CONDITION,
                default=rule.get(RULE_CONDITION, "equals"),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=list(CONDITIONS),
                    translation_key="condition",
                )
            ),
            vol.Required(
                RULE_VALUE,
                default=rule.get(RULE_VALUE, vol.UNDEFINED),
            ): value_selector,
            vol.Required(
                RULE_TASK_TITLE,
                default=rule.get(RULE_TASK_TITLE, vol.UNDEFINED),
            ): selector.TextSelector(),
            vol.Required(
                RULE_DIFFICULTY,
                default=rule.get(RULE_DIFFICULTY, "medium"),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=list(DIFFICULTIES),
                    translation_key="difficulty",
                )
            ),
            vol.Required(
                RULE_TRIGGER_MODE,
                default=rule.get(RULE_TRIGGER_MODE, "edge"),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=list(TRIGGER_MODES),
                    translation_key="trigger_mode",
                )
            ),
            vol.Required(
                RULE_COOLDOWN,
                default=rule.get(RULE_COOLDOWN, DEFAULT_COOLDOWN),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=525600,
                    step=1,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                RULE_ASSIGNEES,
                default=selected_assignees,
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=assignee_options,
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                RULE_DUE_DATE_OFFSET,
                default=str(rule.get(RULE_DUE_DATE_OFFSET, "-1")),
            ): selector.SelectSelector(selector.SelectSelectorConfig(options=due_date_options)),
            vol.Optional(
                RULE_NOTIFY_APP,
                default=rule.get(RULE_NOTIFY_APP, True),
            ): selector.BooleanSelector(),
            vol.Optional(
                RULE_ENABLED,
                default=rule.get(RULE_ENABLED, True),
            ): selector.BooleanSelector(),
        }
        if rule:
            schema[vol.Optional("delete_rule", default=False)] = selector.BooleanSelector()
        return vol.Schema(schema)

    async def async_step_add_rule_details(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Configure details and save a new rule."""
        if self._current_entity_id is None:
            return await self.async_step_add_rule()
        if user_input is not None:
            raw_rule = {
                **user_input,
                RULE_ENTITY_ID: self._current_entity_id,
            }
            self._rules.append(normalize_rule(raw_rule, default_trigger_mode="edge"))
            return self.async_create_entry(title="", data={CONF_RULES: self._rules})
        schema = await self._get_form_schema(self._current_entity_id)
        return self.async_show_form(
            step_id="add_rule_details",
            data_schema=schema,
            errors=self._form_error,
        )

    async def async_step_manage_rules(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Select an existing rule to edit or delete."""
        if user_input is not None:
            value = user_input["rule_index"]
            if value == "none":
                return await self.async_step_init()
            self._selected_rule_index = int(value)
            return await self.async_step_edit_rule()
        options = [
            selector.SelectOptionDict(
                value=str(index),
                label=f"{rule.get(RULE_TASK_TITLE, 'Quest')} ({rule.get(RULE_ENTITY_ID)})",
            )
            for index, rule in enumerate(self._rules)
        ]
        if not options:
            options = [selector.SelectOptionDict(value="none", label="No rules configured")]
        return self.async_show_form(
            step_id="manage_rules",
            data_schema=vol.Schema(
                {
                    vol.Required("rule_index"): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=options)
                    )
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
        entity_id = rule[RULE_ENTITY_ID]
        if user_input is not None:
            if user_input.pop("delete_rule", False):
                self._rules.pop(self._selected_rule_index)
            else:
                updated = normalize_rule(
                    {
                        **user_input,
                        RULE_ID: rule[RULE_ID],
                        RULE_ENTITY_ID: entity_id,
                    },
                    default_trigger_mode="edge",
                )
                self._rules[self._selected_rule_index] = updated
            return self.async_create_entry(title="", data={CONF_RULES: self._rules})
        schema = await self._get_form_schema(entity_id, rule)
        return self.async_show_form(
            step_id="edit_rule",
            data_schema=schema,
            errors=self._form_error,
        )
