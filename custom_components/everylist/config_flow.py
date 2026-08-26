"""Config flow for EveryList.

Which lists to expose is discovered automatically from the token itself:
``GET /tokens/me`` (a PAT-only endpoint — a login session has no per-list
grant to report) returns the authenticating PAT's own scope, one
``{listId, role}`` grant per list it was minted against in EveryList's
``Settings -> Access Tokens``. Each granted list's display name then comes
from ``GET /lists/:id``, which doubles as a scope-check (a token unscoped to
a list 404s there — see ``foundational/PLAN.md``).
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_URL
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import EveryListAuthError, EveryListClient, EveryListConnectionError
from .const import CONF_LIST_IDS, DOMAIN

_USER_SCHEMA = vol.Schema({vol.Required(CONF_URL): str, vol.Required(CONF_ACCESS_TOKEN): str})
_TOKEN_SCHEMA = vol.Schema({vol.Required(CONF_ACCESS_TOKEN): str})


def _entry_title(lists: dict[str, dict[str, str | None]]) -> str:
    return "EveryList (" + ", ".join(entry["name"] for entry in lists.values()) + ")"


class EveryListConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for EveryList."""

    VERSION = 1

    async def _discover_lists(
        self, base_url: str, token: str
    ) -> tuple[str | None, dict[str, dict[str, str | None]]]:
        """Returns ``(error_code, lists)`` — ``error_code`` is ``None`` on success."""
        session = async_get_clientsession(self.hass)
        client = EveryListClient(session, base_url, token)
        lists: dict[str, dict[str, str | None]] = {}
        try:
            grants = await client.get_my_grants()
            for grant in grants:
                list_info = await client.get_list(grant.list_id)
                lists[str(grant.list_id)] = {
                    "name": list_info.name,
                    "role": grant.role,
                    "icon": list_info.icon,
                }
        except EveryListConnectionError:
            return "cannot_connect", {}
        except EveryListAuthError:
            return "invalid_auth", {}

        if not lists:
            return "no_lists_granted", {}
        return None, lists

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial setup step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            error, lists = await self._discover_lists(
                user_input[CONF_URL], user_input[CONF_ACCESS_TOKEN]
            )
            if error is None:
                await self.async_set_unique_id(user_input[CONF_URL])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=_entry_title(lists),
                    data={
                        CONF_URL: user_input[CONF_URL],
                        CONF_ACCESS_TOKEN: user_input[CONF_ACCESS_TOKEN],
                        CONF_LIST_IDS: lists,
                    },
                )
            errors["base"] = error

        return self.async_show_form(step_id="user", data_schema=_USER_SCHEMA, errors=errors)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle a reauth request, e.g. after the token is revoked or expires.

        Also the way to change which lists this entry exposes: mint a token
        scoped to the new set of lists and reauthenticate with it — the
        entry's list set is re-discovered fresh from whatever the new token
        grants, rather than re-validated against the old one.
        """
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()
        if user_input is not None:
            error, lists = await self._discover_lists(
                reauth_entry.data[CONF_URL], user_input[CONF_ACCESS_TOKEN]
            )
            if error is None:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data={
                        **reauth_entry.data,
                        CONF_ACCESS_TOKEN: user_input[CONF_ACCESS_TOKEN],
                        CONF_LIST_IDS: lists,
                    },
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm", data_schema=_TOKEN_SCHEMA, errors=errors
        )
