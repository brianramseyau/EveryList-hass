"""Config flow for EveryList.

The API has no "introspect my own grants" endpoint (a Stage 0 design gap
noted in ``foundational/PLAN.md``), so the user supplies the same list IDs
they picked when minting the Personal Access Token in EveryList's
``Settings -> Access Tokens``. Validation calls ``GET /lists/:id`` for each
one — this both confirms the token works and (since that endpoint is scope-
checked) that the token is actually granted access to it, and doubles as the
source of each list's display name.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_URL
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import EveryListAuthError, EveryListClient, EveryListConnectionError
from .const import CONF_LIST_IDS, CONF_LIST_IDS_INPUT, DOMAIN

_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): str,
        vol.Required(CONF_ACCESS_TOKEN): str,
        vol.Required(CONF_LIST_IDS_INPUT): str,
    }
)
_TOKEN_SCHEMA = vol.Schema({vol.Required(CONF_ACCESS_TOKEN): str})


def _parse_list_ids(raw: str) -> list[int]:
    """Raises ``ValueError`` if any comma-separated part isn't an integer."""
    return [int(part.strip()) for part in raw.split(",") if part.strip()]


def _entry_title(list_names: dict[str, str]) -> str:
    return "EveryList (" + ", ".join(list_names.values()) + ")"


class EveryListConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for EveryList."""

    VERSION = 1

    async def _fetch_list_names(
        self, base_url: str, token: str, list_ids: list[int]
    ) -> dict[str, str]:
        """Raises :class:`EveryListConnectionError` or :class:`EveryListAuthError`."""
        session = async_get_clientsession(self.hass)
        client = EveryListClient(session, base_url, token)
        names: dict[str, str] = {}
        for list_id in list_ids:
            list_info = await client.get_list(list_id)
            names[str(list_id)] = list_info.name
        return names

    async def _validate(
        self, base_url: str, token: str, raw_list_ids: str
    ) -> tuple[str | None, dict[str, str]]:
        """Returns ``(error_code, list_names)`` — ``error_code`` is ``None`` on success."""
        try:
            list_ids = _parse_list_ids(raw_list_ids)
        except ValueError:
            return "invalid_list_ids_format", {}
        if not list_ids:
            return "no_list_ids", {}

        try:
            list_names = await self._fetch_list_names(base_url, token, list_ids)
        except EveryListConnectionError:
            return "cannot_connect", {}
        except EveryListAuthError:
            return "invalid_auth_or_scope", {}

        return None, list_names

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial setup step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            error, list_names = await self._validate(
                user_input[CONF_URL], user_input[CONF_ACCESS_TOKEN], user_input[CONF_LIST_IDS_INPUT]
            )
            if error is None:
                await self.async_set_unique_id(user_input[CONF_URL])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=_entry_title(list_names),
                    data={
                        CONF_URL: user_input[CONF_URL],
                        CONF_ACCESS_TOKEN: user_input[CONF_ACCESS_TOKEN],
                        CONF_LIST_IDS: list_names,
                    },
                )
            errors["base"] = error

        return self.async_show_form(step_id="user", data_schema=_USER_SCHEMA, errors=errors)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle a reauth request, e.g. after the token is revoked or expires."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()
        if user_input is not None:
            list_ids_csv = ",".join(reauth_entry.data[CONF_LIST_IDS])
            error, list_names = await self._validate(
                reauth_entry.data[CONF_URL], user_input[CONF_ACCESS_TOKEN], list_ids_csv
            )
            if error is None:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data={
                        **reauth_entry.data,
                        CONF_ACCESS_TOKEN: user_input[CONF_ACCESS_TOKEN],
                        CONF_LIST_IDS: list_names,
                    },
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm", data_schema=_TOKEN_SCHEMA, errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user change which lists this entry exposes, without a new token."""
        errors: dict[str, str] = {}
        reconfigure_entry = self._get_reconfigure_entry()
        if user_input is not None:
            error, list_names = await self._validate(
                reconfigure_entry.data[CONF_URL],
                reconfigure_entry.data[CONF_ACCESS_TOKEN],
                user_input[CONF_LIST_IDS_INPUT],
            )
            if error is None:
                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    data={**reconfigure_entry.data, CONF_LIST_IDS: list_names},
                )
            errors["base"] = error

        current_ids = ",".join(reconfigure_entry.data[CONF_LIST_IDS])
        schema = vol.Schema({vol.Required(CONF_LIST_IDS_INPUT, default=current_ids): str})
        return self.async_show_form(step_id="reconfigure", data_schema=schema, errors=errors)
