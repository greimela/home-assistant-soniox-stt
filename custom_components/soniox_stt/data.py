"""Runtime data for the Soniox STT integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry

from .api import SonioxApiClient


@dataclass
class SonioxRuntimeData:
    """Runtime data stored on a Soniox config entry."""

    client: SonioxApiClient
    supported_languages: tuple[str, ...]


type SonioxConfigEntry = ConfigEntry[SonioxRuntimeData]
