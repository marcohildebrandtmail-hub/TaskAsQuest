"""Tests for the Task as Quest config flow."""

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant import config_entries, data_entry_flow
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.taskasquest.const import (
    CONF_APP_URL,
    CONF_AUTH_TOKEN,
    CONF_LOGIN_NAME,
    CONF_PASSWORD,
    CONF_RULES,
    CONF_USER_ID,
    DOMAIN,
    RULE_ENTITY_ID,
)


async def test_user_flow_creates_entry(hass: HomeAssistant) -> None:
    """Successful authentication creates a versioned config entry."""
    with patch("custom_components.taskasquest.config_flow.TaskAsQuestClient") as client_class:
        client = client_class.return_value
        client.authenticate = AsyncMock()
        client.async_unlock_protected_fields = AsyncMock()
        client.user_id = "user-id"
        client.token = "token"

        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )
        assert result["type"] is data_entry_flow.FlowResultType.FORM

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_APP_URL: "https://example.test/",
                CONF_LOGIN_NAME: "Hero#0001",
                CONF_PASSWORD: "password",
            },
        )

    assert result["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["title"] == "Hero#0001"
    assert result["data"][CONF_APP_URL] == "https://example.test"
    assert result["data"][CONF_AUTH_TOKEN] == "token"
    assert result["data"][CONF_USER_ID] == "user-id"


async def test_user_flow_rejects_invalid_url(hass: HomeAssistant) -> None:
    """Only HTTP(S) server URLs reach the API client."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_APP_URL: "file:///etc/passwd",
            CONF_LOGIN_NAME: "Hero#0001",
            CONF_PASSWORD: "password",
        },
    )

    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_url"}


async def test_options_flow_builds_rule_detail_selectors(hass: HomeAssistant) -> None:
    """The complete add-rule UI can be serialized by Home Assistant."""
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
    coordinator = MagicMock()
    coordinator.client.get_companions = AsyncMock(return_value={"friend": "Friend#0002"})
    entry.runtime_data = coordinator
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is data_entry_flow.FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"next_step_id": "add_rule"},
    )
    assert result["type"] is data_entry_flow.FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {RULE_ENTITY_ID: "sensor.plant"},
    )

    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "add_rule_details"
    coordinator.client.get_companions.assert_awaited_once()
