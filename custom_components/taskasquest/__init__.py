"""Task as Quest Home Assistant integration."""

from __future__ import annotations

from typing import Any, cast

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .app_client import TaskAsQuestClient
from .const import (
    CONDITIONS,
    CONF_APP_URL,
    CONF_AUTH_TOKEN,
    CONF_CONFIG_ENTRY_ID,
    CONF_LOGIN_NAME,
    CONF_PASSWORD,
    CONF_RULES,
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
    RULE_NOTIFY_APP,
    RULE_TASK_TITLE,
    RULE_TRIGGER_MODE,
    RULE_VALUE,
    SERVICE_ADD_RULES,
    SERVICE_CREATE_QUEST,
    TRIGGER_MODES,
)
from .coordinator import TaskAsQuestCoordinator
from .exceptions import (
    TaskAsQuestApiError,
    TaskAsQuestAuthenticationError,
    TaskAsQuestCannotConnectError,
    TaskAsQuestEncryptionError,
    TaskAsQuestError,
    TaskAsQuestRateLimitError,
    TaskAsQuestTotpRequiredError,
)
from .panel import async_register_dashboard
from .rules import normalize_rule, rule_signature

PLATFORMS = (Platform.SENSOR, Platform.TODO)

TaskAsQuestConfigEntry = ConfigEntry[TaskAsQuestCoordinator]

SERVICE_SCHEMA_CREATE_QUEST = vol.Schema(
    {
        vol.Optional(CONF_CONFIG_ENTRY_ID): cv.string,
        vol.Required("title"): cv.string,
        vol.Optional("difficulty", default="medium"): vol.In(DIFFICULTIES),
        vol.Optional("description"): cv.string,
        vol.Optional("due_date"): cv.string,
        vol.Optional("assignees", default=[]): vol.All(
            cv.ensure_list,
            [cv.string],
        ),
        vol.Optional("notify_app", default=False): cv.boolean,
    }
)

RULE_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(RULE_ENTITY_ID): cv.entity_id,
        vol.Required(RULE_CONDITION): vol.In(CONDITIONS),
        vol.Required(RULE_VALUE): vol.Coerce(str),
        vol.Required(RULE_TASK_TITLE): cv.string,
        vol.Optional(RULE_DIFFICULTY, default="medium"): vol.In(DIFFICULTIES),
        vol.Optional(RULE_COOLDOWN, default=DEFAULT_COOLDOWN): vol.All(
            vol.Coerce(int),
            vol.Range(min=0),
        ),
        vol.Optional(RULE_ASSIGNEES, default=[]): vol.All(
            cv.ensure_list,
            [cv.string],
        ),
        vol.Optional(RULE_DUE_DATE_OFFSET, default="-1"): vol.Coerce(str),
        vol.Optional(RULE_NOTIFY_APP, default=True): cv.boolean,
        vol.Optional(RULE_ENABLED, default=True): cv.boolean,
        vol.Optional(RULE_TRIGGER_MODE, default="edge"): vol.In(TRIGGER_MODES),
    }
)

SERVICE_SCHEMA_ADD_RULES = vol.Schema(
    {
        vol.Optional(CONF_CONFIG_ENTRY_ID): cv.string,
        vol.Required(CONF_RULES): vol.All(cv.ensure_list, [RULE_SERVICE_SCHEMA]),
    }
)


def _loaded_coordinator(hass: HomeAssistant, config_entry_id: str | None) -> TaskAsQuestCoordinator:
    """Resolve an action call to exactly one loaded config entry."""
    entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]
    if config_entry_id:
        entries = [entry for entry in entries if entry.entry_id == config_entry_id]
    if not entries:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="no_loaded_account",
        )
    if len(entries) > 1:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="multiple_loaded_accounts",
        )
    return cast(TaskAsQuestConfigEntry, entries[0]).runtime_data


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Register Task as Quest actions once for the integration domain."""
    await async_register_dashboard(hass)

    async def handle_create_quest(call: ServiceCall) -> dict[str, Any]:
        coordinator = _loaded_coordinator(
            hass,
            call.data.get(CONF_CONFIG_ENTRY_ID),
        )
        try:
            task = await coordinator.client.create_task(
                title=call.data["title"],
                difficulty=call.data["difficulty"],
                description=call.data.get("description"),
                due_date=call.data.get("due_date"),
                assignees=call.data["assignees"],
                notify_app=call.data["notify_app"],
            )
            await coordinator.async_request_refresh()
        except TaskAsQuestAuthenticationError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="authentication_expired",
            ) from err
        except TaskAsQuestError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="create_quest_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        return {
            "task_id": task["id"],
            "warnings": task.get("warnings", []),
        }

    async def handle_add_rules(call: ServiceCall) -> dict[str, int]:
        coordinator = _loaded_coordinator(
            hass,
            call.data.get(CONF_CONFIG_ENTRY_ID),
        )
        entry = coordinator.config_entry
        current_rules = list(entry.options.get(CONF_RULES, []))
        signatures = {rule_signature(rule) for rule in current_rules}
        added = 0
        skipped = 0
        for raw_rule in call.data[CONF_RULES]:
            rule = normalize_rule(raw_rule, default_trigger_mode="edge")
            signature = rule_signature(rule)
            if signature in signatures:
                skipped += 1
                continue
            current_rules.append(rule)
            signatures.add(signature)
            added += 1
        if added:
            hass.config_entries.async_update_entry(
                entry,
                options={**entry.options, CONF_RULES: current_rules},
            )
        return {"added": added, "skipped": skipped}

    if not hass.services.has_service(DOMAIN, SERVICE_CREATE_QUEST):
        hass.services.async_register(
            DOMAIN,
            SERVICE_CREATE_QUEST,
            handle_create_quest,
            schema=SERVICE_SCHEMA_CREATE_QUEST,
            supports_response=SupportsResponse.OPTIONAL,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_ADD_RULES):
        hass.services.async_register(
            DOMAIN,
            SERVICE_ADD_RULES,
            handle_add_rules,
            schema=SERVICE_SCHEMA_ADD_RULES,
            supports_response=SupportsResponse.OPTIONAL,
        )
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TaskAsQuestConfigEntry,
) -> bool:
    """Set up Task as Quest from a config entry."""
    client = TaskAsQuestClient(
        entry.data.get(CONF_APP_URL, DEFAULT_APP_URL),
        async_get_clientsession(hass),
        hass.async_add_executor_job,
    )
    token = entry.data.get(CONF_AUTH_TOKEN)
    user_id = entry.data.get(CONF_USER_ID)
    try:
        if token and user_id:
            client.restore_session(token, user_id)
            try:
                await client.refresh_auth(force=True)
            except TaskAsQuestAuthenticationError:
                await client.authenticate(
                    entry.data.get(CONF_LOGIN_NAME, ""),
                    entry.data[CONF_PASSWORD],
                )
        else:
            await client.authenticate(
                entry.data.get(CONF_LOGIN_NAME, ""),
                entry.data[CONF_PASSWORD],
            )
        await client.async_unlock_protected_fields(entry.data[CONF_PASSWORD])
    except (TaskAsQuestAuthenticationError, TaskAsQuestTotpRequiredError) as err:
        raise ConfigEntryAuthFailed("Task as Quest authentication failed") from err
    except TaskAsQuestEncryptionError as err:
        raise ConfigEntryAuthFailed("Task as Quest encryption could not be unlocked") from err
    except (TaskAsQuestCannotConnectError, TaskAsQuestRateLimitError) as err:
        raise ConfigEntryNotReady("Task as Quest is temporarily unavailable") from err
    except TaskAsQuestApiError as err:
        raise ConfigEntryError(f"Task as Quest setup failed: {err}") from err

    hass.config_entries.async_update_entry(
        entry,
        data={
            **entry.data,
            CONF_AUTH_TOKEN: client.token,
            CONF_USER_ID: client.user_id,
        },
    )

    raw_rules = list(entry.options.get(CONF_RULES, []))
    rules = [normalize_rule(rule, default_trigger_mode="level") for rule in raw_rules]
    if rules != raw_rules:
        hass.config_entries.async_update_entry(
            entry,
            options={**entry.options, CONF_RULES: rules},
        )

    coordinator = TaskAsQuestCoordinator(hass, entry, client, rules)
    entry.runtime_data = coordinator
    await coordinator.async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.async_start()
    entry.async_on_unload(coordinator.async_shutdown)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_migrate_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Migrate legacy entries and rules to the version 2 data model."""
    if entry.version > 2:
        return False
    if entry.version < 2:
        data = dict(entry.data)
        data.pop("recovery_code", None)
        rules = [
            normalize_rule(rule, default_trigger_mode="level")
            for rule in entry.options.get(CONF_RULES, [])
        ]
        hass.config_entries.async_update_entry(
            entry,
            data=data,
            options={**entry.options, CONF_RULES: rules},
            version=2,
        )
    return True


async def _async_update_listener(
    hass: HomeAssistant,
    entry: TaskAsQuestConfigEntry,
) -> None:
    """Apply rule option changes without reloading network resources."""
    rules = [
        normalize_rule(rule, default_trigger_mode="level")
        for rule in entry.options.get(CONF_RULES, [])
    ]
    entry.runtime_data.update_rules(rules)
    entry.runtime_data.async_publish_rule_update()


async def async_unload_entry(
    hass: HomeAssistant,
    entry: TaskAsQuestConfigEntry,
) -> bool:
    """Unload a Task as Quest config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
