"""Tests for the EveryList config flow."""

from __future__ import annotations

import aiohttp
import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.everylist.const import CONF_LIST_IDS, DOMAIN

from .conftest import BASE_URL, LIST_ID, LIST_NAME, TOKEN, list_json, token_me_json
from .fake_aiohttp import FakeSession

LIST_URL = f"{BASE_URL}/api/v1/lists/{LIST_ID}"
TOKEN_ME_URL = f"{BASE_URL}/api/v1/tokens/me"


@pytest.fixture(autouse=True)
def session(monkeypatch: pytest.MonkeyPatch) -> FakeSession:
    """Patch every ``async_get_clientsession(hass)`` call in this integration to a FakeSession."""
    fake = FakeSession()
    monkeypatch.setattr(
        "custom_components.everylist.config_flow.async_get_clientsession", lambda hass: fake
    )
    monkeypatch.setattr("custom_components.everylist.async_get_clientsession", lambda hass: fake)
    return fake


async def _start_user_flow(hass: HomeAssistant) -> dict:
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def _configure(hass: HomeAssistant, flow_id: str, access_token: str = TOKEN) -> dict:
    return await hass.config_entries.flow.async_configure(
        flow_id, {"url": BASE_URL, "access_token": access_token}
    )


async def test_user_flow_success(hass: HomeAssistant, session: FakeSession) -> None:
    result = await _start_user_flow(hass)
    assert result["type"] is FlowResultType.FORM

    session.add_response("GET", TOKEN_ME_URL, json_body={"data": token_me_json()})
    session.add_response("GET", LIST_URL, json_body={"data": list_json()})
    result = await _configure(hass, result["flow_id"])

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"EveryList ({LIST_NAME})"
    assert result["data"] == {
        "url": BASE_URL,
        "access_token": TOKEN,
        CONF_LIST_IDS: {str(LIST_ID): {"name": LIST_NAME, "role": "editor", "icon": None}},
    }


async def test_user_flow_multiple_lists_with_mixed_roles(
    hass: HomeAssistant, session: FakeSession
) -> None:
    result = await _start_user_flow(hass)

    session.add_response(
        "GET",
        TOKEN_ME_URL,
        json_body={
            "data": token_me_json(
                grants=[{"listId": LIST_ID, "role": "editor"}, {"listId": 5, "role": "viewer"}]
            )
        },
    )
    session.add_response(
        "GET", LIST_URL, json_body={"data": list_json(list_id=LIST_ID, name="Groceries")}
    )
    session.add_response(
        "GET",
        f"{BASE_URL}/api/v1/lists/5",
        json_body={"data": list_json(list_id=5, name="Hardware")},
    )
    result = await _configure(hass, result["flow_id"])

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_LIST_IDS] == {
        str(LIST_ID): {"name": "Groceries", "role": "editor", "icon": None},
        "5": {"name": "Hardware", "role": "viewer", "icon": None},
    }


async def test_user_flow_carries_list_icon(hass: HomeAssistant, session: FakeSession) -> None:
    result = await _start_user_flow(hass)

    session.add_response("GET", TOKEN_ME_URL, json_body={"data": token_me_json()})
    session.add_response("GET", LIST_URL, json_body={"data": list_json(icon="cartOutline")})
    result = await _configure(hass, result["flow_id"])

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_LIST_IDS] == {
        str(LIST_ID): {"name": LIST_NAME, "role": "editor", "icon": "cartOutline"}
    }


async def test_user_flow_cannot_connect(hass: HomeAssistant, session: FakeSession) -> None:
    result = await _start_user_flow(hass)

    session.add_exception("GET", TOKEN_ME_URL, aiohttp.ClientConnectionError("boom"))
    result = await _configure(hass, result["flow_id"])

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_invalid_auth_on_bad_token(
    hass: HomeAssistant, session: FakeSession
) -> None:
    result = await _start_user_flow(hass)

    session.add_response("GET", TOKEN_ME_URL, status=401)
    result = await _configure(hass, result["flow_id"])

    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_invalid_auth_when_a_granted_list_is_gone(
    hass: HomeAssistant, session: FakeSession
) -> None:
    """The token itself is valid, but a list it's scoped to has since been deleted."""
    result = await _start_user_flow(hass)

    session.add_response("GET", TOKEN_ME_URL, json_body={"data": token_me_json()})
    session.add_response("GET", LIST_URL, status=404)
    result = await _configure(hass, result["flow_id"])

    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_no_lists_granted(hass: HomeAssistant, session: FakeSession) -> None:
    result = await _start_user_flow(hass)

    session.add_response("GET", TOKEN_ME_URL, json_body={"data": token_me_json(grants=[])})
    result = await _configure(hass, result["flow_id"])

    assert result["errors"] == {"base": "no_lists_granted"}


async def test_user_flow_aborts_on_duplicate_base_url(
    hass: HomeAssistant, session: FakeSession
) -> None:
    existing = MockConfigEntry(
        domain=DOMAIN,
        unique_id=BASE_URL,
        data={
            "url": BASE_URL,
            "access_token": TOKEN,
            CONF_LIST_IDS: {str(LIST_ID): {"name": LIST_NAME, "role": "editor"}},
        },
    )
    existing.add_to_hass(hass)

    result = await _start_user_flow(hass)
    session.add_response("GET", TOKEN_ME_URL, json_body={"data": token_me_json()})
    session.add_response("GET", LIST_URL, json_body={"data": list_json()})
    result = await _configure(hass, result["flow_id"])

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_flow_success_updates_token_and_rediscovers_lists(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, session: FakeSession
) -> None:
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    session.add_response(
        "GET",
        TOKEN_ME_URL,
        json_body={"data": token_me_json(grants=[{"listId": 5, "role": "viewer"}])},
    )
    session.add_response(
        "GET",
        f"{BASE_URL}/api/v1/lists/5",
        json_body={"data": list_json(list_id=5, name="Hardware")},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"access_token": "elt_new_token"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data["access_token"] == "elt_new_token"
    assert mock_config_entry.data[CONF_LIST_IDS] == {
        "5": {"name": "Hardware", "role": "viewer", "icon": None}
    }


async def test_reauth_flow_error_keeps_form_open(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, session: FakeSession
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reauth_flow(hass)

    session.add_response("GET", TOKEN_ME_URL, status=401)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"access_token": "elt_bad_token"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
