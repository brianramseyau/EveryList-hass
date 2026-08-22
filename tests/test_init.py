"""Tests for setting up and unloading the EveryList config entry."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.everylist import EveryListRuntimeData, async_unload_entry

from .conftest import BASE_URL, LIST_ID, item_json
from .fake_aiohttp import FakeSession

ITEMS_URL = f"{BASE_URL}/api/v1/lists/{LIST_ID}/items"


@pytest.fixture(autouse=True)
def session(monkeypatch: pytest.MonkeyPatch) -> FakeSession:
    fake = FakeSession()
    monkeypatch.setattr("custom_components.everylist.async_get_clientsession", lambda hass: fake)
    return fake


async def test_setup_and_unload_entry(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, session: FakeSession
) -> None:
    mock_config_entry.add_to_hass(hass)
    session.add_response("GET", ITEMS_URL, json_body={"data": [item_json()]})

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("todo.groceries") is not None

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
    assert hass.states.get("todo.groceries").state == STATE_UNAVAILABLE


async def test_setup_entry_auth_failure_starts_reauth(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, session: FakeSession
) -> None:
    mock_config_entry.add_to_hass(hass)
    session.add_response("GET", ITEMS_URL, status=401)

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(flow["context"]["source"] == "reauth" for flow in flows)


async def test_setup_entry_connection_failure_retries(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, session: FakeSession
) -> None:
    mock_config_entry.add_to_hass(hass)
    session.add_exception("GET", ITEMS_URL, aiohttp.ClientConnectionError("boom"))

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_unload_entry_leaves_coordinator_running_if_platforms_dont_unload(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """A platform that refuses to unload must not still tear down the shared coordinator."""
    coordinator = AsyncMock()
    mock_config_entry.runtime_data = EveryListRuntimeData(
        client=AsyncMock(), coordinator=coordinator
    )

    with patch.object(hass.config_entries, "async_unload_platforms", AsyncMock(return_value=False)):
        result = await async_unload_entry(hass, mock_config_entry)

    assert result is False
    coordinator.async_shutdown.assert_not_called()
