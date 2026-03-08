"""API client for the Soniox speech-to-text service."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Sequence
from typing import Any

import aiohttp

from ..const import DEFAULT_MODEL, POLL_INTERVAL_SECONDS, TRANSCRIPTION_TIMEOUT_SECONDS


class SonioxError(Exception):
    """Base exception for Soniox API errors."""


class SonioxCommunicationError(SonioxError):
    """Communication with the Soniox API failed."""


class SonioxAuthenticationError(SonioxError):
    """Authentication with the Soniox API failed."""


class SonioxTranscriptionError(SonioxError):
    """Soniox rejected or failed a transcription request."""


class SonioxApiClient:
    """Thin async client for the Soniox REST API."""

    def __init__(
        self,
        api_key: str,
        session: aiohttp.ClientSession,
        model: str = DEFAULT_MODEL,
    ) -> None:
        """Initialize the Soniox client."""
        self._api_key = api_key
        self._session = session
        self._model = model

    async def async_get_supported_languages(self) -> tuple[str, ...]:
        """Return the supported languages for the configured async model."""
        response = await self._request("get", "/v1/models")
        models: Sequence[dict[str, Any]] = response.get("models", [])

        for model in models:
            if model.get("id") == self._model:
                return self._extract_language_codes(model)

        async_models = [
            model
            for model in models
            if isinstance(model.get("id"), str) and str(model["id"]).startswith("stt-async")
        ]
        if async_models:
            return self._extract_language_codes(async_models[0])

        msg = f"Soniox model {self._model} is not available for this API key"
        raise SonioxError(msg)

    async def async_transcribe(
        self,
        *,
        audio: bytes,
        filename: str,
        content_type: str,
        language: str | None,
    ) -> str:
        """Upload audio to Soniox and return the final transcript text."""
        file_id: str | None = None
        transcription_id: str | None = None

        try:
            file_id = await self._upload_file(audio=audio, filename=filename, content_type=content_type)
            transcription_id = await self._create_transcription(file_id=file_id, language=language)
            await self._wait_until_completed(transcription_id)
            transcript = await self._get_transcript(transcription_id)
        finally:
            if transcription_id is not None:
                await self._best_effort_delete_transcription(transcription_id)
            elif file_id is not None:
                await self._best_effort_delete_file(file_id)

        return transcript

    async def _upload_file(
        self,
        *,
        audio: bytes,
        filename: str,
        content_type: str,
    ) -> str:
        """Upload audio bytes and return the Soniox file id."""
        form = aiohttp.FormData()
        form.add_field("file", audio, filename=filename, content_type=content_type)
        response = await self._request("post", "/v1/files", data=form)

        file_id = response.get("id")
        if not isinstance(file_id, str):
            msg = "Soniox upload response did not include a file id"
            raise SonioxError(msg)
        return file_id

    async def _create_transcription(self, *, file_id: str, language: str | None) -> str:
        """Create a transcription job and return its id."""
        payload: dict[str, Any] = {
            "model": self._model,
            "file_id": file_id,
        }
        if language:
            payload["language_hints"] = [language]
            payload["language_hints_strict"] = True

        response = await self._request("post", "/v1/transcriptions", json=payload)
        transcription_id = response.get("id")
        if not isinstance(transcription_id, str):
            msg = "Soniox transcription response did not include an id"
            raise SonioxError(msg)
        return transcription_id

    async def _wait_until_completed(self, transcription_id: str) -> None:
        """Poll Soniox until the transcription finishes or fails."""
        async with asyncio.timeout(TRANSCRIPTION_TIMEOUT_SECONDS):
            while True:
                response = await self._request("get", f"/v1/transcriptions/{transcription_id}")
                status = response.get("status")

                if status == "completed":
                    return
                if status == "error":
                    msg = response.get("error_message", "Soniox returned an unknown transcription error")
                    raise SonioxTranscriptionError(msg)

                await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _get_transcript(self, transcription_id: str) -> str:
        """Fetch and render the final Soniox transcript."""
        response = await self._request("get", f"/v1/transcriptions/{transcription_id}/transcript")
        tokens = response.get("tokens", [])

        if not isinstance(tokens, list):
            msg = "Soniox transcript response did not include tokens"
            raise SonioxError(msg)

        return self._render_tokens(tokens).strip()

    def _render_tokens(self, tokens: list[dict[str, Any]]) -> str:
        """Convert Soniox tokens into readable text."""
        parts: list[str] = []

        for token in tokens:
            text = token.get("text")
            if isinstance(text, str):
                parts.append(text)

        return "".join(parts)

    def _extract_language_codes(self, model: dict[str, Any]) -> tuple[str, ...]:
        """Extract ISO language codes from a Soniox model payload."""
        languages = model.get("languages", [])
        if not isinstance(languages, list):
            msg = "Soniox model response did not include a valid languages list"
            raise SonioxError(msg)

        codes: list[str] = []
        for language in languages:
            if isinstance(language, dict):
                code = language.get("code")
                if isinstance(code, str):
                    codes.append(code)

        return tuple(sorted(codes))

    async def _best_effort_delete_transcription(self, transcription_id: str) -> None:
        """Delete a transcription without masking the original result."""
        try:
            await self._request("delete", f"/v1/transcriptions/{transcription_id}", allow_empty=True)
        except SonioxError:
            return

    async def _best_effort_delete_file(self, file_id: str) -> None:
        """Delete an uploaded file without masking the original result."""
        try:
            await self._request("delete", f"/v1/files/{file_id}", allow_empty=True)
        except SonioxError:
            return

    async def _request(
        self,
        method: str,
        path: str,
        *,
        allow_empty: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Perform an authenticated request against the Soniox API."""
        try:
            async with asyncio.timeout(10):
                async with self._session.request(
                    method=method,
                    url=f"https://api.soniox.com{path}",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    **kwargs,
                ) as response:
                    if response.status in (401, 403):
                        msg = "Soniox API key is invalid"
                        raise SonioxAuthenticationError(msg)

                    response.raise_for_status()

                    if allow_empty and response.status == 204:
                        return None

                    return await response.json()
        except TimeoutError as exception:
            msg = f"Timed out while talking to Soniox: {exception}"
            raise SonioxCommunicationError(msg) from exception
        except (aiohttp.ClientError, socket.gaierror) as exception:
            msg = f"Error talking to Soniox: {exception}"
            raise SonioxCommunicationError(msg) from exception
        except SonioxError:
            raise
        except Exception as exception:
            msg = f"Unexpected Soniox API error: {exception}"
            raise SonioxError(msg) from exception
