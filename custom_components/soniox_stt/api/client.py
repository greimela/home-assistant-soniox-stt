"""SDK-backed client for the Soniox speech-to-text service."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, AsyncIterator
import json
import logging
import ssl
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
from soniox.types.realtime import RealtimeEvent, RealtimeSTTConfig
from soniox.utils import render_tokens
from websockets.asyncio.client import connect
from websockets.asyncio.connection import Connection
from websockets.exceptions import ConnectionClosed

from custom_components.soniox_stt.const import DEFAULT_MODEL

CHUNK_SIZE_BYTES: Final = 4096
KEEP_ALIVE_SECONDS: Final = 10.0
LOGGER = logging.getLogger(__name__)


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
        self._ssl_context: ssl.SSLContext | None = None

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
        audio_stream: AsyncIterable[bytes],
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

        final_tokens: list[Token] = []
        non_final_tokens: list[Token] = []
        transcript = ""
        last_event: RealtimeEvent | None = None
        sender_task: asyncio.Task[tuple[int, int]] | None = None
        keep_alive_task: asyncio.Task[None] | None = None
        chunks_sent = 0
        bytes_sent = 0

        LOGGER.info(
            "Starting Soniox realtime STT model=%s language=%s audio_format=%s sample_rate=%s channels=%s",
            self._model,
            language,
            config.audio_format,
            config.sample_rate,
            config.num_channels,
        )

        try:
            async with await self._async_connect_realtime(config) as session:
                sender_task = asyncio.create_task(self._send_audio(session, audio_stream))
                keep_alive_task = asyncio.create_task(self._keep_alive(session))

                async for event in self._receive_events(session):
                    last_event = event
                    LOGGER.info(
                        "Soniox realtime event finished=%s tokens=%s error=%r final_audio_proc_ms=%s total_audio_proc_ms=%s",
                        event.finished,
                        len(event.tokens),
                        event.error_message,
                        event.final_audio_proc_ms,
                        event.total_audio_proc_ms,
                    )
                    if event.error_message:
                        raise SonioxTranscriptionError(event.error_message)

                    if event.tokens:
                        final_tokens.extend(token for token in event.tokens if token.is_final)
                        non_final_tokens = [token for token in event.tokens if not token.is_final]
                        rendered = render_tokens(final_tokens, non_final_tokens).strip()
                        if rendered:
                            transcript = rendered

                    if event.finished:
                        break

                if sender_task is not None:
                    chunks_sent, bytes_sent = await sender_task
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
            details = ""
            if last_event is not None:
                details = (
                    f" (finished={last_event.finished}, "
                    f"tokens={len(last_event.tokens)}, "
                    f"error={last_event.error_message!r})"
                )
            msg = f"Soniox did not return any transcript text{details}"
            LOGGER.info(
                "Soniox realtime STT finished without transcript model=%s language=%s chunks_sent=%s bytes_sent=%s%s",
                self._model,
                language,
                chunks_sent,
                bytes_sent,
                details,
            )
            raise SonioxTranscriptionError(msg)

        LOGGER.info(
            "Soniox realtime STT succeeded model=%s language=%s chunks_sent=%s bytes_sent=%s transcript_chars=%s",
            self._model,
            language,
            chunks_sent,
            bytes_sent,
            len(transcript),
        )
        return transcript

    async def _send_audio(self, session: Connection, audio_stream: AsyncIterable[bytes]) -> tuple[int, int]:
        """Send audio chunks to the active Soniox realtime session."""
        chunk_count = 0
        byte_count = 0

        async for chunk in audio_stream:
            if chunk:
                chunk_bytes = bytes(chunk)
                chunk_count += 1
                byte_count += len(chunk_bytes)
                await session.send(chunk_bytes)

        LOGGER.info(
            "Finished sending audio to Soniox realtime websocket chunks=%s bytes=%s",
            chunk_count,
            byte_count,
        )
        await session.send(json.dumps({"type": "finalize"}))
        await session.send("")
        LOGGER.info("Sent finalize and finish to Soniox realtime websocket")
        return chunk_count, byte_count

    async def _keep_alive(self, session: Connection) -> None:
        """Keep the realtime websocket alive while audio is streaming."""
        while True:
            await asyncio.sleep(KEEP_ALIVE_SECONDS)
            await session.send(json.dumps({"type": "keepalive"}))

    async def _async_connect_realtime(self, config: RealtimeSTTConfig) -> Connection:
        """Open a realtime websocket using a prebuilt SSL context."""
        ssl_context = await self._async_get_ssl_context()
        LOGGER.info("Connecting to Soniox realtime websocket url=%s", self._client.websocket_base_url)
        session = await connect(
            self._client.websocket_base_url,
            ssl=ssl_context,
        )
        try:
            await session.send(json.dumps(config.build_payload(self._api_key).model_dump(exclude_none=True)))
        except Exception:
            await session.close()
            raise
        else:
            LOGGER.info("Connected to Soniox realtime websocket")
            return session

    async def _async_get_ssl_context(self) -> ssl.SSLContext:
        """Create the default SSL context outside the event loop."""
        if self._ssl_context is None:
            self._ssl_context = await asyncio.to_thread(ssl.create_default_context)
        return self._ssl_context

    async def _receive_events(self, session: Connection) -> AsyncIterator[RealtimeEvent]:
        """Yield parsed Soniox realtime events from the websocket."""
        while True:
            try:
                raw = await session.recv()
            except ConnectionClosed:
                break

            if raw in ("", b""):
                break

            yield RealtimeEvent.validate_event(raw)
