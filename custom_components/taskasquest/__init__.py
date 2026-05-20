"""Task as Quest — Home Assistant Integration."""

import logging
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_AUTH_TOKEN,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_PB_URL,
    CONF_RECOVERY_CODE,
    CONF_RULES,
    CONF_USER_ID,
    DOMAIN,
)
from .coordinator import TaskAsQuestCoordinator
from .pocketbase_client import PocketBaseClient

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

    client = PocketBaseClient(entry.data[CONF_PB_URL])

    # Erst Token probieren, dann Passwort
    token = entry.data.get(CONF_AUTH_TOKEN, "")
    user_id = entry.data.get(CONF_USER_ID, "")
    authenticated = False

    if token and user_id:
        authenticated = await client.authenticate_with_token(token, user_id)

    if not authenticated:
        authenticated = await client.authenticate(
            entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD]
        )

    if not authenticated:
        _LOGGER.error("Task as Quest: Authentifizierung fehlgeschlagen")
        await client.close()
        return False

    if not client.unlock_task_crypto(entry.data.get(CONF_RECOVERY_CODE, "")):
        _LOGGER.error("Task as Quest: Verschluesselungs-Code fehlt oder ist ungueltig")
        await client.close()
        return False

    # Token in config aktualisieren
    if client.token != token:
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_AUTH_TOKEN: client.token, CONF_USER_ID: client.user_id},
        )

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
