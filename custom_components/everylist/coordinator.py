"""Polling coordinator for EveryList lists."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import EveryListAuthError, EveryListClient, EveryListConnectionError, EveryListItem
from .const import DEFAULT_SCAN_INTERVAL_SECONDS, DOMAIN

_LOGGER = logging.getLogger(__name__)


class EveryListCoordinator(DataUpdateCoordinator[dict[int, list[EveryListItem]]]):
    """Polls every configured list's items on a single shared interval.

    A 401/404 from any list (revoked token, or the token's scope changed to
    no longer cover a previously-working list) is surfaced as
    :class:`~homeassistant.exceptions.ConfigEntryAuthFailed`, which triggers
    HA's reauth flow instead of leaving entities silently stale — see
    "Auth and reauth" in ``foundational/PLAN.md``.
    """

    def __init__(self, hass: HomeAssistant, client: EveryListClient, list_ids: list[int]) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL_SECONDS),
        )
        self.client = client
        self.list_ids = list_ids

    async def _async_update_data(self) -> dict[int, list[EveryListItem]]:
        try:
            return {list_id: await self.client.get_items(list_id) for list_id in self.list_ids}
        except EveryListAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except EveryListConnectionError as err:
            raise UpdateFailed(str(err)) from err
