"""Tests for the EveryList polling coordinator."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.everylist.api import (
    EveryListAuthError,
    EveryListConnectionError,
    EveryListItem,
)
from custom_components.everylist.coordinator import EveryListCoordinator

from .conftest import LIST_ID, item_json


async def test_update_data_success(hass: HomeAssistant) -> None:
    client = AsyncMock()
    client.get_items.return_value = [EveryListItem.from_json(item_json())]
    coordinator = EveryListCoordinator(hass, client, [LIST_ID])

    data = await coordinator._async_update_data()

    assert list(data) == [LIST_ID]
    assert data[LIST_ID][0].name == "Milk"


async def test_update_data_auth_error_raises_config_entry_auth_failed(hass: HomeAssistant) -> None:
    client = AsyncMock()
    client.get_items.side_effect = EveryListAuthError("nope")
    coordinator = EveryListCoordinator(hass, client, [LIST_ID])

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_update_data_connection_error_raises_update_failed(hass: HomeAssistant) -> None:
    client = AsyncMock()
    client.get_items.side_effect = EveryListConnectionError("down")
    coordinator = EveryListCoordinator(hass, client, [LIST_ID])

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
