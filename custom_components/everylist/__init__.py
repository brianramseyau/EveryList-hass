"""The EveryList integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry, ConfigEntryNotReady
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_URL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import EveryListAuthError, EveryListClient, EveryListConnectionError
from .const import CONF_LIST_IDS
from .coordinator import EveryListCoordinator

PLATFORMS: list[Platform] = [Platform.TODO]

type EveryListConfigEntry = ConfigEntry["EveryListRuntimeData"]


@dataclass
class EveryListRuntimeData:
    """Runtime state stashed on the config entry — no ``hass.data`` bucket needed."""

    client: EveryListClient
    coordinator: EveryListCoordinator
    lists: dict[str, dict[str, str | None]]


async def _refresh_list_metadata(
    client: EveryListClient, lists: dict[str, dict[str, str | None]]
) -> dict[str, dict[str, str | None]]:
    """Re-fetch each list's name/icon, preserving the stored PAT role.

    Name and icon are otherwise only captured at config/reauth time; re-reading
    them on every entry setup (HA restart or integration reload) picks up
    renames and icon changes without a polling schedule. A 401/404 here means
    the list was deleted or the PAT's scope shrank, which — matching the
    coordinator — surfaces as reauth rather than a silently stale entity.
    """
    refreshed: dict[str, dict[str, str | None]] = {}
    try:
        for list_id, info in lists.items():
            list_info = await client.get_list(int(list_id))
            refreshed[list_id] = {
                "name": list_info.name,
                "icon": list_info.icon,
                "role": info["role"],
            }
    except EveryListAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except EveryListConnectionError as err:
        raise ConfigEntryNotReady(str(err)) from err
    return refreshed


async def async_setup_entry(hass: HomeAssistant, entry: EveryListConfigEntry) -> bool:
    """Set up EveryList from a config entry."""
    session = async_get_clientsession(hass)
    client = EveryListClient(session, entry.data[CONF_URL], entry.data[CONF_ACCESS_TOKEN])
    lists = await _refresh_list_metadata(client, entry.data[CONF_LIST_IDS])
    list_ids = [int(list_id) for list_id in lists]
    coordinator = EveryListCoordinator(hass, client, list_ids)

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = EveryListRuntimeData(client=client, coordinator=coordinator, lists=lists)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EveryListConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.coordinator.async_shutdown()
    return unloaded
