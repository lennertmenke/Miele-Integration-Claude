"""Test the OAuth config flow."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.components.application_credentials import (
    ClientCredential,
    async_import_client_credential,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.setup import async_setup_component

from custom_components.miele_plus.const import DOMAIN, OAUTH2_AUTHORIZE, OAUTH2_TOKEN

REDIRECT = "https://example.com/auth/external/callback"


async def test_full_flow(
    hass: HomeAssistant, hass_client_no_auth, aioclient_mock, current_request_with_host
) -> None:
    assert await async_setup_component(hass, "application_credentials", {})
    await async_import_client_credential(hass, DOMAIN, ClientCredential("cid", "secret"), DOMAIN)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    state = config_entry_oauth2_flow._encode_jwt(
        hass, {"flow_id": result["flow_id"], "redirect_uri": REDIRECT}
    )
    assert result["type"] is FlowResultType.EXTERNAL_STEP
    assert result["url"].startswith(f"{OAUTH2_AUTHORIZE}?response_type=code&client_id=cid")
    assert "vg=" in result["url"]
    assert "scope=openid+mcs_thirdparty_read+mcs_thirdparty_write" in result["url"]

    client = await hass_client_no_auth()
    resp = await client.get(f"/auth/external/callback?code=abcd&state={state}")
    assert resp.status == 200

    aioclient_mock.post(
        OAUTH2_TOKEN,
        json={
            "refresh_token": "refresh",
            "access_token": "access",
            "type": "Bearer",
            "expires_in": 60,
        },
    )
    with patch("custom_components.miele_plus.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["token"]["access_token"] == "access"
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.unique_id == DOMAIN


async def test_options_flow(hass: HomeAssistant, setup_integration) -> None:
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "language": "en",
            "use_push": False,
            "poll_interval": 45,
            "stale_grace": 5,
            "power_off_on_finish": True,
            "power_off_delay": 0,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    coordinator = setup_integration.runtime_data
    assert coordinator.api.language == "en"
    assert coordinator.update_interval.total_seconds() == 30  # washer running
    assert coordinator.power_off_on_finish is True
