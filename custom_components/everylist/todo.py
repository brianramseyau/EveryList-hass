"""TodoListEntity platform for EveryList — one entity per configured list."""

from __future__ import annotations

import difflib

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import EveryListConfigEntry
from .api import EveryListConflictError, EveryListItem
from .const import CONF_LIST_IDS
from .coordinator import EveryListCoordinator

# A close-but-not-exact transcription ("miilk") is accepted as a match to an
# existing recent name; below this, "milk" vs "milkshake" would also match,
# which is too loose for a mishear-correction heuristic.
_FUZZY_MATCH_CUTOFF = 0.8


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EveryListConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one TodoListEntity per list the config entry covers."""
    coordinator = entry.runtime_data.coordinator
    list_names: dict[str, str] = entry.data[CONF_LIST_IDS]

    async_add_entities(
        EveryListTodoListEntity(coordinator, entry, list_id=int(list_id), name=name)
        for list_id, name in list_names.items()
    )


class EveryListTodoListEntity(CoordinatorEntity[EveryListCoordinator], TodoListEntity):
    """A single EveryList list, exposed as a HA todo list."""

    _attr_has_entity_name = True
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
    )

    def __init__(
        self,
        coordinator: EveryListCoordinator,
        entry: ConfigEntry,
        *,
        list_id: int,
        name: str,
    ) -> None:
        super().__init__(coordinator)
        self._list_id = list_id
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}-{list_id}"

    @property
    def todo_items(self) -> list[TodoItem]:
        items = self.coordinator.data.get(self._list_id, [])
        return [_to_todo_item(item) for item in items]

    def _find_item(self, item_id: str | None) -> EveryListItem:
        for item in self.coordinator.data.get(self._list_id, []):
            if str(item.id) == item_id:
                return item
        raise ValueError(f"No item {item_id} on list {self._list_id}")

    async def async_create_todo_item(self, item: TodoItem) -> None:
        name = await self._resolve_create_name(item.summary or "")
        await self.coordinator.client.create_item(self._list_id, name)
        await self.coordinator.async_request_refresh()

    async def _resolve_create_name(self, requested_name: str) -> str:
        """Fuzzy-match a near-miss transcription against recent names before creating.

        The API's own dedup is an exact ``LOWER(TRIM(name))`` match and only
        catches exact repeats, not a mishear like "miilk" vs "milk" — see
        "API surface used" in ``foundational/PLAN.md``.
        """
        recent_names = await self.coordinator.client.get_recent_names(self._list_id)
        # Compared case-insensitively — a transcription's capitalization is no
        # more reliable than its spelling — but the original casing from the
        # API is what's actually created, so the match is looked up by its
        # lowercased key rather than returned directly.
        by_lower_name = {name.lower(): name for name in recent_names}
        matches = difflib.get_close_matches(
            requested_name.lower(), by_lower_name, n=1, cutoff=_FUZZY_MATCH_CUTOFF
        )
        return by_lower_name[matches[0]] if matches else requested_name

    async def async_update_todo_item(self, item: TodoItem) -> None:
        current = self._find_item(item.uid)
        fields: dict[str, object] = {}
        if item.summary is not None and item.summary != current.name:
            fields["name"] = item.summary
        if item.status is not None:
            fields["checked"] = item.status == TodoItemStatus.COMPLETED
        await self._update_with_retry(current, fields)

    async def _update_with_retry(self, item: EveryListItem, fields: dict[str, object]) -> None:
        """Apply an update, refetching and retrying once on a stale-version conflict."""
        try:
            await self.coordinator.client.update_item(
                self._list_id, item.id, expected_version=item.version, **fields
            )
        except EveryListConflictError as err:
            await self.coordinator.client.update_item(
                self._list_id, item.id, expected_version=err.item.version, **fields
            )
        await self.coordinator.async_request_refresh()

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        for uid in uids:
            item = self._find_item(uid)
            await self._delete_with_retry(item)
        await self.coordinator.async_request_refresh()

    async def _delete_with_retry(self, item: EveryListItem) -> None:
        try:
            await self.coordinator.client.delete_item(
                self._list_id, item.id, expected_version=item.version
            )
        except EveryListConflictError as err:
            await self.coordinator.client.delete_item(
                self._list_id, item.id, expected_version=err.item.version
            )


def _to_todo_item(item: EveryListItem) -> TodoItem:
    return TodoItem(
        uid=str(item.id),
        summary=item.name,
        status=TodoItemStatus.COMPLETED if item.checked else TodoItemStatus.NEEDS_ACTION,
        description=item.notes,
    )
