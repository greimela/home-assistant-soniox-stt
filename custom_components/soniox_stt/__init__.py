"""The Soniox STT integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
import homeassistant.helpers.config_validation as cv

from .api import SonioxApiClient, SonioxAuthenticationError, SonioxCommunicationError
from .const import DOMAIN
from .data import SonioxConfigEntry, SonioxRuntimeData

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

PLATFORMS: list[Platform] = [Platform.STT]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Soniox STT integration."""
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SonioxConfigEntry,
) -> bool:
    """Set up Soniox from a config entry."""
    client = SonioxApiClient(
        api_key=entry.data[CONF_API_KEY],
    )

    try:
        supported_languages = await client.async_get_supported_languages()
    except SonioxAuthenticationError as err:
        raise ConfigEntryAuthFailed from err
    except SonioxCommunicationError as err:
        raise ConfigEntryNotReady from err

    entry.runtime_data = SonioxRuntimeData(
        client=client,
        supported_languages=supported_languages,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: SonioxConfigEntry,
) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.client.async_aclose()
    return unload_ok


async def async_reload_entry(
    hass: HomeAssistant,
    entry: SonioxConfigEntry,
) -> None:
    """Reload a config entry."""
    await hass.config_entries.async_reload(entry.entry_id)
