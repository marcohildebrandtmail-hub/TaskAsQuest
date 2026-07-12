"""Task as Quest — Home Assistant Integration."""

import logging
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_APP_URL,
    CONF_AUTH_TOKEN,
    CONF_PASSWORD,
    CONF_LOGIN_NAME,
    CONF_RECOVERY_CODE,
    CONF_RULES,
    CONF_USER_ID,
    DEFAULT_APP_URL,
    DOMAIN,
)
from .coordinator import TaskAsQuestCoordinator
from .app_client import TaskAsQuestClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.TODO]

SERVICE_CREATE_QUEST = "create_quest"
SERVICE_SCHEMA_CREATE_QUEST = vol.Schema(
    {
        vol.Required("title"): cv.string,
        vol.Optional("difficulty", default="medium"): vol.In(["easy", "medium", "hard", "epic"]),
        vol.Optional("description"): cv.string,
        vol.Optional("due_date"): cv.string,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Task as Quest from config entry."""
    hass.data.setdefault(DOMAIN, {})

    client = TaskAsQuestClient(entry.data.get(CONF_APP_URL, DEFAULT_APP_URL))
    token = entry.data.get(CONF_AUTH_TOKEN, "")
    user_id = entry.data.get(CONF_USER_ID, "")
    authenticated = False
    if token and user_id:
        authenticated = await client.authenticate_with_token(token, user_id)

    if not authenticated:
        login_name = entry.data.get(CONF_LOGIN_NAME, "")
        authenticated, _ = await client.authenticate(login_name, entry.data[CONF_PASSWORD])

    if not authenticated:
        await client.close()
        raise ConfigEntryAuthFailed(
            "Task as Quest session expired; reauthentication required"
        )

    hass.config_entries.async_update_entry(
        entry,
        data={
            **entry.data,
            CONF_AUTH_TOKEN: client.token,
            CONF_USER_ID: client.user_id,
        },
    )

    if not client.unlock_protected_fields(entry.data.get(CONF_RECOVERY_CODE, "")):
        _LOGGER.error("Task as Quest: Verschluesselungs-Code fehlt oder ist ungueltig")
        await client.close()
        return False

    rules = entry.options.get(CONF_RULES, [])
    coordinator = TaskAsQuestCoordinator(hass, entry, client, rules)

    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    async def handle_create_quest(call: ServiceCall) -> None:
        """Handle the service call."""
        await client.create_task(
            title=call.data["title"],
            difficulty=call.data["difficulty"],
            description=call.data.get("description"),
            due_date=call.data.get("due_date"),
        )
        await coordinator.async_refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_QUEST,
        handle_create_quest,
        schema=SERVICE_SCHEMA_CREATE_QUEST,
    )

    SERVICE_ADD_RULES = "add_rules"
    SERVICE_SCHEMA_ADD_RULES = vol.Schema(
        {
            vol.Required("rules"): vol.All(
                cv.ensure_list,
                [
                    vol.Schema({
                        vol.Required("entity_id"): cv.string,
                        vol.Required("condition"): vol.In(["equals", "not_equals", "below", "above"]),
                        vol.Required("value"): cv.string,
                        vol.Required("task_title"): cv.string,
                        vol.Optional("difficulty", default="medium"): vol.In(["easy", "medium", "hard", "epic"]),
                        vol.Optional("cooldown", default=1440): int,
                        vol.Optional("assignees", default=[]): vol.All(cv.ensure_list, [cv.string]),
                        vol.Optional("due_date_offset", default="-1"): cv.string,
                        vol.Optional("notify_app", default=False): cv.boolean,
                        vol.Optional("enabled", default=True): cv.boolean,
                    })
                ]
            )
        }
    )

    async def handle_add_rules(call: ServiceCall) -> None:
        """Add new rules to the integration."""
        new_rules = call.data["rules"]
        current_options = dict(entry.options)
        rules = list(current_options.get(CONF_RULES, []))
        
        # Avoid exact duplicates by entity_id
        existing_entities = {r.get('entity_id') for r in rules}
        
        added_count = 0
        for rule in new_rules:
            if rule["entity_id"] not in existing_entities:
                rules.append(rule)
                added_count += 1
                
        if added_count > 0:
            current_options[CONF_RULES] = rules
            hass.config_entries.async_update_entry(entry, options=current_options)
            _LOGGER.info("Task as Quest: Added %d new rules via service call.", added_count)

    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_RULES,
        handle_add_rules,
        schema=SERVICE_SCHEMA_ADD_RULES,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Options-Updates live uebernehmen
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    coordinator: TaskAsQuestCoordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.update_rules(entry.options.get(CONF_RULES, []))
    _LOGGER.info("Task as Quest: Regeln aktualisiert (%d)", len(coordinator.rules))


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: TaskAsQuestCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.client.close()
    return unload_ok
