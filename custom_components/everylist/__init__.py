"""The EveryList integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_URL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import EveryListClient
from .const import CONF_LIST_IDS
from .coordinator import EveryListCoordinator

PLATFORMS: list[Platform] = [Platform.TODO]

type EveryListConfigEntry = ConfigEntry["EveryListRuntimeData"]


@dataclass
class EveryListRuntimeData:
    """Runtime state stashed on the config entry — no ``hass.data`` bucket needed."""

    client: EveryListClient
    coordinator: EveryListCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: EveryListConfigEntry) -> bool:
    """Set up EveryList from a config entry."""
    session = async_get_clientsession(hass)
    client = EveryListClient(session, entry.data[CONF_URL], entry.data[CONF_ACCESS_TOKEN])
    list_ids = [int(list_id) for list_id in entry.data[CONF_LIST_IDS]]
    coordinator = EveryListCoordinator(hass, client, list_ids)

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = EveryListRuntimeData(client=client, coordinator=coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EveryListConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.coordinator.async_shutdown()
    return unloaded
