"""Diagnostics for the Soniox STT integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.const import CONF_API_KEY
from homeassistant.helpers.redact import async_redact_data

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import SonioxConfigEntry

TO_REDACT = {CONF_API_KEY}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: SonioxConfigEntry,
) -> dict[str, Any]:
    """Return redacted diagnostics for a Soniox config entry."""
    return async_redact_data(
        {
            "entry": {
                "title": entry.title,
                "data": dict(entry.data),
                "options": dict(entry.options),
            },
            "runtime": {
                "supported_languages": entry.runtime_data.supported_languages,
            },
        },
        TO_REDACT,
    )
