"""Integration lifecycle tests for Task as Quest."""

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.taskasquest.const import (
    CONF_APP_URL,
    CONF_LOGIN_NAME,
    CONF_PASSWORD,
    CONF_RULES,
    DOMAIN,
    SERVICE_ADD_RULES,
    SERVICE_CREATE_QUEST,
)


async def test_setup_and_unload_entry(hass: HomeAssistant) -> None:
    """A real config entry sets up entities, actions and cleanly unloads."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_APP_URL: "https://example.test",
            CONF_LOGIN_NAME: "Hero#0001",
            CONF_PASSWORD: "password",
        },
        options={CONF_RULES: []},
        unique_id="user-id",
        version=2,
    )
    entry.add_to_hass(hass)

    with patch("custom_components.taskasquest.TaskAsQuestClient") as client_class:
        client = client_class.return_value
        client.authenticate = AsyncMock()
        client.async_unlock_protected_fields = AsyncMock()
        client.refresh_auth = AsyncMock()
        client.get_open_tasks = AsyncMock(return_value=[])
        client.token = "token"
        client.user_id = "user-id"
        client.base_url = "https://example.test"

        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert hass.services.has_service(DOMAIN, SERVICE_CREATE_QUEST)
    assert hass.services.has_service(DOMAIN, SERVICE_ADD_RULES)
    assert entry.runtime_data.last_update_success

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
