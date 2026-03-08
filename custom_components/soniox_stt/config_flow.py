"""Config flow for the Soniox STT integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY, CONF_LANGUAGE
from homeassistant.helpers import selector

from .api import SonioxApiClient, SonioxAuthenticationError, SonioxCommunicationError
from .const import AUTO_LANGUAGE, DOMAIN, LANGUAGE_NAMES, TITLE

ERROR_MAP = {
    SonioxAuthenticationError: "auth",
    SonioxCommunicationError: "cannot_connect",
}


class SonioxSTTOptionsFlow(config_entries.OptionsFlow):
    """Handle Soniox STT options."""

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Manage the language handling option."""
        languages = self.config_entry.runtime_data.supported_languages

        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_LANGUAGE,
                        default=self.config_entry.options.get(
                            CONF_LANGUAGE,
                            self.config_entry.data.get(CONF_LANGUAGE, AUTO_LANGUAGE),
                        ),
                    ): _build_language_selector(languages),
                }
            ),
        )


class SonioxSTTConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Soniox STT."""

    VERSION = 1

    _api_key: str | None = None
    _languages: tuple[str, ...] = ()
    _step_context: str = "user"

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> SonioxSTTOptionsFlow:
        """Return the options flow for this config entry."""
        return SonioxSTTOptionsFlow()

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial setup flow."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        return await self._async_step_api_key(user_input=user_input, step_id="user")

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle Soniox API key changes."""
        self._step_context = "reconfigure"
        return await self._async_step_api_key(user_input=user_input, step_id="reconfigure")

    async def async_step_reauth(
        self,
        entry_data: Mapping[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Start the reauthentication flow."""
        self._step_context = "reauth"
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Confirm a Soniox API key reauthentication."""
        self._step_context = "reauth"
        return await self._async_step_api_key(user_input=user_input, step_id="reauth_confirm")

    async def async_step_language(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Select the language mode after validating the API key."""
        if self._api_key is None:
            return await self.async_step_user()

        if user_input is not None:
            data = {
                CONF_API_KEY: self._api_key,
                CONF_LANGUAGE: user_input[CONF_LANGUAGE],
            }

            if self._step_context == "user":
                return self.async_create_entry(title=TITLE, data=data)

            entry = self._get_reauth_entry() if self._step_context == "reauth" else self._get_reconfigure_entry()
            return self.async_update_reload_and_abort(entry, data=data)

        default_language = AUTO_LANGUAGE
        if self._step_context != "user":
            entry = self._get_reauth_entry() if self._step_context == "reauth" else self._get_reconfigure_entry()
            default_language = entry.options.get(CONF_LANGUAGE, entry.data.get(CONF_LANGUAGE, AUTO_LANGUAGE))

        return self.async_show_form(
            step_id="language",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LANGUAGE, default=default_language): _build_language_selector(self._languages),
                }
            ),
        )

    async def _async_step_api_key(
        self,
        *,
        user_input: dict[str, Any] | None,
        step_id: str,
    ) -> config_entries.ConfigFlowResult:
        """Validate a Soniox API key before continuing."""
        errors: dict[str, str] = {}

        if user_input is not None:
            client = SonioxApiClient(
                api_key=user_input[CONF_API_KEY],
            )
            try:
                self._languages = await client.async_get_supported_languages()
            except tuple(ERROR_MAP) as err:
                errors["base"] = ERROR_MAP[type(err)]
            else:
                self._api_key = user_input[CONF_API_KEY]
                return await self.async_step_language()

        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): str}),
            errors=errors,
        )


def _build_language_selector(languages: tuple[str, ...]) -> selector.SelectSelector:
    """Build the language selector shown in setup and options."""
    options = [
        selector.SelectOptionDict(
            value=AUTO_LANGUAGE,
            label="Automatic (use the Assist pipeline language)",
        ),
        *[
            selector.SelectOptionDict(
                value=language,
                label=f"{LANGUAGE_NAMES.get(language, language)} ({language})",
            )
            for language in languages
        ],
    ]

    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


__all__ = ["SonioxSTTConfigFlow"]
