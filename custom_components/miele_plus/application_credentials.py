"""Application credentials platform for Miele Plus."""

from homeassistant.components.application_credentials import AuthorizationServer
from homeassistant.core import HomeAssistant

from .const import OAUTH2_AUTHORIZE, OAUTH2_TOKEN


async def async_get_authorization_server(hass: HomeAssistant) -> AuthorizationServer:
    """Return the Miele authorization server."""
    return AuthorizationServer(authorize_url=OAUTH2_AUTHORIZE, token_url=OAUTH2_TOKEN)


async def async_get_description_placeholders(hass: HomeAssistant) -> dict[str, str]:
    """Return description placeholders for the credentials dialog."""
    return {
        "developer_url": "https://www.miele.com/f/com/en/register_api.aspx",
        "redirect_url": "https://my.home-assistant.io/redirect/oauth",
    }
