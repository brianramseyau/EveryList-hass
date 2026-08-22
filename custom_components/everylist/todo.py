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


_WRITE_FEATURES = (
    TodoListEntityFeature.CREATE_TODO_ITEM
    | TodoListEntityFeature.UPDATE_TODO_ITEM
    | TodoListEntityFeature.DELETE_TODO_ITEM
    | TodoListEntityFeature.MOVE_TODO_ITEM
    | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EveryListConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one TodoListEntity per list the config entry covers."""
    coordinator = entry.runtime_data.coordinator
    lists: dict[str, dict[str, str]] = entry.data[CONF_LIST_IDS]

    async_add_entities(
        EveryListTodoListEntity(
            coordinator, entry, list_id=int(list_id), name=info["name"], role=info["role"]
        )
        for list_id, info in lists.items()
    )


class EveryListTodoListEntity(CoordinatorEntity[EveryListCoordinator], TodoListEntity):
    """A single EveryList list, exposed as a HA todo list.

    A ``viewer``-scoped PAT grant gets a read-only entity — the API itself
    would 403 a write from such a token, so ``supported_features`` reflects
    that up front rather than letting the user hit a failed service call.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EveryListCoordinator,
        entry: ConfigEntry,
        *,
        list_id: int,
        name: str,
        role: str,
    ) -> None:
        super().__init__(coordinator)
        self._list_id = list_id
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}-{list_id}"
        self._attr_supported_features = (
            _WRITE_FEATURES if role == "editor" else TodoListEntityFeature(0)
        )

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
        if item.description != current.notes:
            fields["notes"] = item.description
        await self._update_with_retry(current, fields)
        await self.coordinator.async_request_refresh()

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

    async def async_move_todo_item(self, uid: str, previous_uid: str | None = None) -> None:
        """Reorder ``uid`` to sit right after ``previous_uid`` (or first, if ``None``).

        EveryList has no bulk-reorder endpoint for items — only a per-item
        ``sortOrder`` on the same ``PATCH`` used for renames/checks — so a
        move is applied by recomputing the whole list's 0..N-1 order and
        writing back only the items whose position actually changed.
        """
        items = list(self.coordinator.data.get(self._list_id, []))
        ordered_ids = [item.id for item in items]
        moved_id = int(uid)
        if moved_id not in ordered_ids:
            raise ValueError(f"No item {uid} on list {self._list_id}")
        ordered_ids.remove(moved_id)

        if previous_uid is None:
            new_index = 0
        else:
            prev_id = int(previous_uid)
            if prev_id not in ordered_ids:
                raise ValueError(f"No item {previous_uid} on list {self._list_id}")
            new_index = ordered_ids.index(prev_id) + 1
        ordered_ids.insert(new_index, moved_id)

        by_id = {item.id: item for item in items}
        for sort_order, item_id in enumerate(ordered_ids):
            item = by_id[item_id]
            if item.sort_order != sort_order:
                await self._update_with_retry(item, {"sortOrder": sort_order})
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
