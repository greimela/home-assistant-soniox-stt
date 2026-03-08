"""SDK-backed client for the Soniox speech-to-text service."""

from __future__ import annotations

import asyncio
from typing import Final

from soniox import AsyncSonioxClient
from soniox.errors import (
    SonioxAPIError as SDKSonioxAPIError,
    SonioxAuthenticationError as SDKSonioxAuthenticationError,
    SonioxError as SDKSonioxError,
    SonioxRealtimeError as SDKSonioxRealtimeError,
    SonioxValidationError as SDKSonioxValidationError,
)
from soniox.types import Token
from soniox.types.realtime import RealtimeSTTConfig
from soniox.utils import render_tokens

from custom_components.soniox_stt.const import DEFAULT_MODEL

CHUNK_SIZE_BYTES: Final = 4096
KEEP_ALIVE_SECONDS: Final = 10.0


class SonioxError(Exception):
    """Base exception for Soniox API errors."""


class SonioxCommunicationError(SonioxError):
    """Communication with the Soniox API failed."""


class SonioxAuthenticationError(SonioxError):
    """Authentication with the Soniox API failed."""


class SonioxTranscriptionError(SonioxError):
    """Soniox rejected or failed a transcription request."""


class SonioxApiClient:
    """Thin async wrapper around the official Soniox SDK."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
    ) -> None:
        """Initialize the Soniox client."""
        self._api_key = api_key
        self._client = AsyncSonioxClient(api_key=api_key)
        self._model = model

    async def async_aclose(self) -> None:
        """Close the underlying Soniox SDK client."""
        await self._client.aclose()

    async def async_get_supported_languages(self) -> tuple[str, ...]:
        """Return the supported languages for the configured realtime model."""
        try:
            response = await self._client.models.list()
        except SDKSonioxAuthenticationError as err:
            raise SonioxAuthenticationError(str(err)) from err
        except (SDKSonioxAPIError, SDKSonioxError, TimeoutError) as err:
            raise SonioxCommunicationError(str(err)) from err

        for model in response.models:
            if model.id == self._model:
                return tuple(sorted(language.code for language in model.languages))

        realtime_models = [model for model in response.models if model.id.startswith("stt-rt")]
        if realtime_models:
            return tuple(sorted(language.code for language in realtime_models[0].languages))

        msg = f"Soniox model {self._model} is not available for this API key"
        raise SonioxError(msg)

    async def async_transcribe_stream(
        self,
        *,
        audio_stream,
        language: str | None,
    ) -> str:
        """Stream audio to Soniox and return the final transcript text."""
        config = RealtimeSTTConfig(
            model=self._model,
            audio_format="pcm_s16le",
            num_channels=1,
            sample_rate=16000,
            language_hints=[language] if language else None,
            language_hints_strict=bool(language),
        )

        transcript = ""
        sender_task: asyncio.Task[None] | None = None
        keep_alive_task: asyncio.Task[None] | None = None

        try:
            async with self._client.realtime.stt.connect(config=config) as session:
                sender_task = asyncio.create_task(self._send_audio(session, audio_stream))
                keep_alive_task = asyncio.create_task(self._keep_alive(session))

                async for event in session.receive_events():
                    if event.error_message:
                        raise SonioxTranscriptionError(event.error_message)

                    if event.tokens:
                        rendered = self._render_event_tokens(event.tokens).strip()
                        if rendered:
                            transcript = rendered

                    if event.finished:
                        break

                if sender_task is not None:
                    await sender_task
        except SDKSonioxAuthenticationError as err:
            raise SonioxAuthenticationError(str(err)) from err
        except (SDKSonioxRealtimeError, SDKSonioxAPIError, SDKSonioxValidationError) as err:
            raise SonioxTranscriptionError(str(err)) from err
        except TimeoutError as err:
            raise SonioxCommunicationError(str(err)) from err
        except SDKSonioxError as err:
            raise SonioxCommunicationError(str(err)) from err
        finally:
            if keep_alive_task is not None:
                keep_alive_task.cancel()
                await asyncio.gather(keep_alive_task, return_exceptions=True)
            if sender_task is not None and not sender_task.done():
                sender_task.cancel()
                await asyncio.gather(sender_task, return_exceptions=True)

        if not transcript:
            msg = "Soniox did not return any transcript text"
            raise SonioxTranscriptionError(msg)

        return transcript

    async def _send_audio(self, session, audio_stream) -> None:
        """Send audio chunks to the active Soniox realtime session."""
        async for chunk in audio_stream:
            if chunk:
                await session.send_byte_chunk(bytes(chunk))
        await session.send_finalize()
        await session.send_finish()

    async def _keep_alive(self, session) -> None:
        """Keep the realtime websocket alive while audio is streaming."""
        while True:
            await asyncio.sleep(KEEP_ALIVE_SECONDS)
            await session.send_keep_alive()

    def _render_event_tokens(self, tokens: list[Token]) -> str:
        """Render a Soniox realtime event into human-readable text."""
        final_tokens = [token for token in tokens if token.is_final]
        non_final_tokens = [token for token in tokens if not token.is_final]
        return render_tokens(final_tokens, non_final_tokens)
