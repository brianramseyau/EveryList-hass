"""Tests for the EveryList config flow."""

from __future__ import annotations

import aiohttp
import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.everylist.const import CONF_LIST_IDS, DOMAIN

from .conftest import BASE_URL, LIST_ID, LIST_NAME, TOKEN, list_json
from .fake_aiohttp import FakeSession

LIST_URL = f"{BASE_URL}/api/v1/lists/{LIST_ID}"


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


async def test_user_flow_success(hass: HomeAssistant, session: FakeSession) -> None:
    result = await _start_user_flow(hass)
    assert result["type"] is FlowResultType.FORM

    session.add_response("GET", LIST_URL, json_body={"data": list_json()})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"url": BASE_URL, "access_token": TOKEN, "list_ids_csv": str(LIST_ID)},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"EveryList ({LIST_NAME})"
    assert result["data"] == {
        "url": BASE_URL,
        "access_token": TOKEN,
        CONF_LIST_IDS: {str(LIST_ID): LIST_NAME},
    }


async def test_user_flow_multiple_lists(hass: HomeAssistant, session: FakeSession) -> None:
    result = await _start_user_flow(hass)

    session.add_response(
        "GET", LIST_URL, json_body={"data": list_json(list_id=LIST_ID, name="Groceries")}
    )
    session.add_response(
        "GET",
        f"{BASE_URL}/api/v1/lists/5",
        json_body={"data": list_json(list_id=5, name="Hardware")},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"url": BASE_URL, "access_token": TOKEN, "list_ids_csv": f"{LIST_ID}, 5"},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_LIST_IDS] == {str(LIST_ID): "Groceries", "5": "Hardware"}


async def test_user_flow_cannot_connect(hass: HomeAssistant, session: FakeSession) -> None:
    result = await _start_user_flow(hass)

    session.add_exception("GET", LIST_URL, aiohttp.ClientConnectionError("boom"))
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"url": BASE_URL, "access_token": TOKEN, "list_ids_csv": str(LIST_ID)},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_invalid_auth_or_scope(hass: HomeAssistant, session: FakeSession) -> None:
    result = await _start_user_flow(hass)

    session.add_response("GET", LIST_URL, status=404)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"url": BASE_URL, "access_token": TOKEN, "list_ids_csv": str(LIST_ID)},
    )

    assert result["errors"] == {"base": "invalid_auth_or_scope"}


async def test_user_flow_invalid_list_ids_format(hass: HomeAssistant) -> None:
    result = await _start_user_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"url": BASE_URL, "access_token": TOKEN, "list_ids_csv": "not-a-number"},
    )

    assert result["errors"] == {"base": "invalid_list_ids_format"}


async def test_user_flow_no_list_ids(hass: HomeAssistant) -> None:
    result = await _start_user_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"url": BASE_URL, "access_token": TOKEN, "list_ids_csv": "  , "},
    )

    assert result["errors"] == {"base": "no_list_ids"}


async def test_user_flow_aborts_on_duplicate_base_url(
    hass: HomeAssistant, session: FakeSession
) -> None:
    existing = MockConfigEntry(
        domain=DOMAIN,
        unique_id=BASE_URL,
        data={"url": BASE_URL, "access_token": TOKEN, CONF_LIST_IDS: {str(LIST_ID): LIST_NAME}},
    )
    existing.add_to_hass(hass)

    result = await _start_user_flow(hass)
    session.add_response("GET", LIST_URL, json_body={"data": list_json()})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"url": BASE_URL, "access_token": TOKEN, "list_ids_csv": str(LIST_ID)},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_flow_success_updates_token(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, session: FakeSession
) -> None:
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    session.add_response("GET", LIST_URL, json_body={"data": list_json()})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"access_token": "elt_new_token"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data["access_token"] == "elt_new_token"


async def test_reauth_flow_error_keeps_form_open(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, session: FakeSession
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reauth_flow(hass)

    session.add_response("GET", LIST_URL, status=401)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"access_token": "elt_bad_token"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth_or_scope"}


async def test_reconfigure_flow_success_updates_lists(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, session: FakeSession
) -> None:
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"

    session.add_response(
        "GET",
        f"{BASE_URL}/api/v1/lists/5",
        json_body={"data": list_json(list_id=5, name="Hardware")},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"list_ids_csv": "5"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_LIST_IDS] == {"5": "Hardware"}


async def test_reconfigure_flow_error_keeps_form_open(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"list_ids_csv": "not-a-number"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_list_ids_format"}
