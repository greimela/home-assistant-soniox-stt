"""Speech-to-text platform for Soniox."""

from __future__ import annotations

from collections.abc import AsyncIterable
from typing import TYPE_CHECKING, Any

from homeassistant.components import stt
from homeassistant.const import CONF_LANGUAGE
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ..api import SonioxAuthenticationError, SonioxCommunicationError, SonioxError, SonioxTranscriptionError
from ..const import AUTO_LANGUAGE, TITLE
from ..data import SonioxConfigEntry

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


AUDIO_CONTENT_TYPES = {
    stt.AudioFormats.WAV: "audio/wav",
    stt.AudioFormats.OGG: "audio/ogg",
}

FILENAME_EXTENSIONS = {
    stt.AudioFormats.WAV: "wav",
    stt.AudioFormats.OGG: "ogg",
}


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
            return [self._configured_language]
        return list(self._available_languages)

    @property
    def supported_formats(self) -> list[stt.AudioFormats]:
        """Return the supported container formats."""
        return [stt.AudioFormats.WAV, stt.AudioFormats.OGG]

    @property
    def supported_codecs(self) -> list[stt.AudioCodecs]:
        """Return the supported audio codecs."""
        return [stt.AudioCodecs.PCM, stt.AudioCodecs.OPUS]

    @property
    def supported_bit_rates(self) -> list[int]:
        """Return the supported audio bit depths."""
        return [16]

    @property
    def supported_sample_rates(self) -> list[int]:
        """Return the supported audio sample rates."""
        return [16000]

    @property
    def supported_channels(self) -> list[int]:
        """Return the supported channel counts."""
        return [1]

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
        return normalized_language in self.supported_languages

    async def async_process_audio_stream(
        self,
        metadata: stt.SpeechMetadata,
        stream: AsyncIterable[bytes],
    ) -> stt.SpeechResult:
        """Transcribe an audio stream with Soniox."""
        content_type = AUDIO_CONTENT_TYPES.get(metadata.format)
        extension = FILENAME_EXTENSIONS.get(metadata.format)

        if content_type is None or extension is None:
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)

        audio = bytearray()
        async for chunk in stream:
            audio.extend(chunk)

        if not audio:
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)

        selected_language = self._configured_language
        if selected_language == AUTO_LANGUAGE:
            selected_language = _normalize_language(metadata.language)

        try:
            text = await self._client.async_transcribe(
                audio=bytes(audio),
                filename=f"assist.{extension}",
                content_type=content_type,
                language=selected_language,
            )
        except (SonioxAuthenticationError, SonioxCommunicationError, SonioxTranscriptionError, SonioxError):
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)

        if not text:
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)

        return stt.SpeechResult(text, stt.SpeechResultState.SUCCESS)


def _normalize_language(language: str) -> str:
    """Normalize a Home Assistant language tag into a Soniox language code."""
    normalized = language.lower().replace("_", "-")
    return normalized.split("-", maxsplit=1)[0]
