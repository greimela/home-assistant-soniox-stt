"""Speech-to-text platform for Soniox."""

from __future__ import annotations

from collections.abc import AsyncIterable
import logging
from typing import TYPE_CHECKING, Any

from custom_components.soniox_stt.api import (
    SonioxAuthenticationError,
    SonioxCommunicationError,
    SonioxError,
    SonioxTranscriptionError,
)
from custom_components.soniox_stt.const import AUTO_LANGUAGE, LANGUAGE_TAGS, TITLE
from custom_components.soniox_stt.data import SonioxConfigEntry
from homeassistant.components import stt
from homeassistant.const import CONF_LANGUAGE
from homeassistant.helpers.entity_platform import AddEntitiesCallback

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: SonioxConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Soniox STT entity."""
    async_add_entities([SonioxSpeechToTextEntity(entry)])


class SonioxSpeechToTextEntity(stt.SpeechToTextEntity):
    """Expose Soniox as a Home Assistant speech-to-text provider."""

    _attr_has_entity_name = True
    _attr_name = "Speech-to-Text"

    def __init__(self, entry: SonioxConfigEntry) -> None:
        """Initialize the entity."""
        self._entry = entry
        self._client = entry.runtime_data.client
        self._available_languages = entry.runtime_data.supported_languages
        self._configured_language = entry.options.get(CONF_LANGUAGE, entry.data.get(CONF_LANGUAGE, AUTO_LANGUAGE))
        self._attr_unique_id = f"{entry.entry_id}_speech_to_text"

    @property
    def supported_languages(self) -> list[str]:
        """Return the supported languages exposed to Assist."""
        if self._configured_language != AUTO_LANGUAGE:
            return _expand_language_tags((self._configured_language,))
        return _expand_language_tags(self._available_languages)

    @property
    def supported_formats(self) -> list[stt.AudioFormats]:
        """Return the supported container formats."""
        return [stt.AudioFormats.WAV]

    @property
    def supported_codecs(self) -> list[stt.AudioCodecs]:
        """Return the supported audio codecs."""
        return [stt.AudioCodecs.PCM]

    @property
    def supported_bit_rates(self) -> list[stt.AudioBitRates]:
        """Return the supported audio bit depths."""
        return [stt.AudioBitRates.BITRATE_16]

    @property
    def supported_sample_rates(self) -> list[stt.AudioSampleRates]:
        """Return the supported audio sample rates."""
        return [stt.AudioSampleRates.SAMPLERATE_16000]

    @property
    def supported_channels(self) -> list[stt.AudioChannels]:
        """Return the supported channel counts."""
        return [stt.AudioChannels.CHANNEL_MONO]

    @property
    def device_info(self) -> dict[str, Any]:
        """Return a virtual device for the provider."""
        return {
            "identifiers": {(self._entry.domain, self._entry.entry_id)},
            "manufacturer": "Soniox",
            "model": TITLE,
            "name": TITLE,
        }

    def check_metadata(self, metadata: stt.SpeechMetadata) -> bool:
        """Allow regional language variants by normalizing to a base language."""
        if metadata.format not in self.supported_formats:
            return False
        if metadata.codec not in self.supported_codecs:
            return False
        if metadata.bit_rate not in self.supported_bit_rates:
            return False
        if metadata.sample_rate not in self.supported_sample_rates:
            return False
        if metadata.channel not in self.supported_channels:
            return False

        normalized_language = _normalize_language(metadata.language)
        if self._configured_language != AUTO_LANGUAGE:
            return normalized_language == self._configured_language
        return normalized_language in self._available_languages

    async def async_process_audio_stream(
        self,
        metadata: stt.SpeechMetadata,
        stream: AsyncIterable[bytes],
    ) -> stt.SpeechResult:
        """Transcribe an audio stream with Soniox."""
        selected_language = self._configured_language
        if selected_language == AUTO_LANGUAGE:
            selected_language = _normalize_language(metadata.language)

        try:
            text = await self._client.async_transcribe_stream(
                audio_stream=stream,
                language=selected_language,
            )
        except (SonioxAuthenticationError, SonioxCommunicationError, SonioxTranscriptionError, SonioxError):
            LOGGER.exception(
                "Soniox STT failed for language=%s metadata=%s",
                selected_language,
                metadata,
            )
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)

        if not text:
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)

        return stt.SpeechResult(text, stt.SpeechResultState.SUCCESS)


def _normalize_language(language: str) -> str:
    """Normalize a Home Assistant language tag into a Soniox language code."""
    normalized = language.lower().replace("_", "-")
    return normalized.split("-", maxsplit=1)[0]


def _expand_language_tags(languages: tuple[str, ...]) -> list[str]:
    """Expand Soniox base language codes to HA-friendly locale tags."""
    expanded: list[str] = []

    for language in languages:
        for tag in LANGUAGE_TAGS.get(language, (language,)):
            if tag not in expanded:
                expanded.append(tag)

    return expanded
