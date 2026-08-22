"""Tests for the EveryList TodoListEntity."""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import AsyncMock

import pytest
from homeassistant.components.todo import TodoItem, TodoItemStatus, TodoListEntityFeature
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.everylist import EveryListRuntimeData
from custom_components.everylist.api import EveryListConflictError, EveryListItem
from custom_components.everylist.const import CONF_LIST_IDS
from custom_components.everylist.coordinator import EveryListCoordinator
from custom_components.everylist.todo import (
    EveryListTodoListEntity,
    _to_todo_item,
    async_setup_entry,
)

from .conftest import LIST_ID, LIST_NAME, item_json


def _milk(**overrides) -> EveryListItem:
    defaults = {"item_id": 1, "name": "Milk", "version": 1}
    return EveryListItem.from_json(item_json(**{**defaults, **overrides}))


@pytest.fixture
async def make_entity(hass: HomeAssistant):
    """Builds a TodoListEntity backed by a coordinator, shut down at teardown.

    `async_request_refresh()` (used by every mutating entity method) goes
    through the coordinator's debouncer, which schedules a callback on the
    event loop — without an explicit shutdown, HA's test harness flags it as
    a lingering timer at the end of the test.
    """
    coordinators: list[EveryListCoordinator] = []

    def _factory(
        client: AsyncMock, items: list[EveryListItem], *, role: str = "editor"
    ) -> EveryListTodoListEntity:
        coordinator = EveryListCoordinator(hass, client, [LIST_ID])
        coordinator.data = {LIST_ID: items}
        coordinators.append(coordinator)
        entry = MockConfigEntry(domain="everylist", entry_id="entry1")
        return EveryListTodoListEntity(
            coordinator, entry, list_id=LIST_ID, name=LIST_NAME, role=role
        )

    yield _factory

    for coordinator in coordinators:
        await coordinator.async_shutdown()


EntityFactory = Callable[..., EveryListTodoListEntity]


async def test_todo_items_reflects_coordinator_data(make_entity: EntityFactory) -> None:
    entity = make_entity(AsyncMock(), [_milk(), _milk(item_id=2, name="Eggs", checked=True)])

    items = entity.todo_items

    assert items[0] == TodoItem(
        uid="1", summary="Milk", status=TodoItemStatus.NEEDS_ACTION, description=None
    )
    assert items[1].status == TodoItemStatus.COMPLETED


async def test_unique_id_scopes_to_entry_and_list(make_entity: EntityFactory) -> None:
    entity = make_entity(AsyncMock(), [])
    assert entity.unique_id == "entry1-3"
    assert entity.name == LIST_NAME


async def test_editor_role_gets_write_features(make_entity: EntityFactory) -> None:
    entity = make_entity(AsyncMock(), [], role="editor")
    assert entity.supported_features == (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.MOVE_TODO_ITEM
        | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
    )


async def test_viewer_role_gets_no_write_features(make_entity: EntityFactory) -> None:
    entity = make_entity(AsyncMock(), [], role="viewer")
    assert entity.supported_features == TodoListEntityFeature(0)


async def test_create_todo_item_exact_name(make_entity: EntityFactory) -> None:
    client = AsyncMock()
    client.get_recent_names.return_value = ["Eggs", "Bread"]
    client.get_items.return_value = [_milk()]
    entity = make_entity(client, [])

    await entity.async_create_todo_item(TodoItem(summary="Milk"))

    client.create_item.assert_awaited_once_with(LIST_ID, "Milk")


async def test_create_todo_item_fuzzy_matches_near_miss_transcription(
    make_entity: EntityFactory,
) -> None:
    client = AsyncMock()
    client.get_recent_names.return_value = ["Milk", "Bread"]
    client.get_items.return_value = []
    entity = make_entity(client, [])

    await entity.async_create_todo_item(TodoItem(summary="miilk"))

    client.create_item.assert_awaited_once_with(LIST_ID, "Milk")


async def test_create_todo_item_no_recent_match_uses_requested_name(
    make_entity: EntityFactory,
) -> None:
    client = AsyncMock()
    client.get_recent_names.return_value = ["Bread", "Eggs"]
    client.get_items.return_value = []
    entity = make_entity(client, [])

    await entity.async_create_todo_item(TodoItem(summary="Peanut butter"))

    client.create_item.assert_awaited_once_with(LIST_ID, "Peanut butter")


async def test_update_todo_item_renames_and_checks(make_entity: EntityFactory) -> None:
    client = AsyncMock()
    client.update_item.return_value = _milk(version=2)
    client.get_items.return_value = [_milk(version=2)]
    entity = make_entity(client, [_milk()])

    await entity.async_update_todo_item(
        TodoItem(uid="1", summary="Whole milk", status=TodoItemStatus.COMPLETED)
    )

    client.update_item.assert_awaited_once_with(
        LIST_ID, 1, expected_version=1, name="Whole milk", checked=True
    )


async def test_update_todo_item_unchanged_name_omits_name_field(
    make_entity: EntityFactory,
) -> None:
    client = AsyncMock()
    client.update_item.return_value = _milk()
    client.get_items.return_value = [_milk()]
    entity = make_entity(client, [_milk()])

    await entity.async_update_todo_item(
        TodoItem(uid="1", summary="Milk", status=TodoItemStatus.NEEDS_ACTION)
    )

    client.update_item.assert_awaited_once_with(LIST_ID, 1, expected_version=1, checked=False)


async def test_update_todo_item_unknown_uid_raises(make_entity: EntityFactory) -> None:
    entity = make_entity(AsyncMock(), [_milk()])

    with pytest.raises(ValueError, match="No item"):
        await entity.async_update_todo_item(TodoItem(uid="999", summary="Ghost"))


async def test_update_todo_item_rename_only_omits_checked_field(
    make_entity: EntityFactory,
) -> None:
    client = AsyncMock()
    client.update_item.return_value = _milk(name="Whole milk")
    client.get_items.return_value = [_milk(name="Whole milk")]
    entity = make_entity(client, [_milk()])

    await entity.async_update_todo_item(TodoItem(uid="1", summary="Whole milk", status=None))

    client.update_item.assert_awaited_once_with(LIST_ID, 1, expected_version=1, name="Whole milk")


async def test_update_todo_item_sets_description(make_entity: EntityFactory) -> None:
    client = AsyncMock()
    client.update_item.return_value = _milk(notes="brand: oat milk")
    client.get_items.return_value = [_milk(notes="brand: oat milk")]
    entity = make_entity(client, [_milk()])

    await entity.async_update_todo_item(
        TodoItem(
            uid="1",
            summary="Milk",
            status=TodoItemStatus.NEEDS_ACTION,
            description="brand: oat milk",
        )
    )

    client.update_item.assert_awaited_once_with(
        LIST_ID, 1, expected_version=1, checked=False, notes="brand: oat milk"
    )


async def test_update_todo_item_clears_description(make_entity: EntityFactory) -> None:
    client = AsyncMock()
    client.update_item.return_value = _milk()
    client.get_items.return_value = [_milk()]
    entity = make_entity(client, [_milk(notes="brand: oat milk")])

    await entity.async_update_todo_item(
        TodoItem(uid="1", summary="Milk", status=TodoItemStatus.NEEDS_ACTION, description=None)
    )

    client.update_item.assert_awaited_once_with(
        LIST_ID, 1, expected_version=1, checked=False, notes=None
    )


async def test_update_todo_item_unchanged_description_omits_notes_field(
    make_entity: EntityFactory,
) -> None:
    client = AsyncMock()
    client.update_item.return_value = _milk(notes="brand: oat milk")
    client.get_items.return_value = [_milk(notes="brand: oat milk")]
    entity = make_entity(client, [_milk(notes="brand: oat milk")])

    await entity.async_update_todo_item(
        TodoItem(
            uid="1",
            summary="Milk",
            status=TodoItemStatus.NEEDS_ACTION,
            description="brand: oat milk",
        )
    )

    client.update_item.assert_awaited_once_with(LIST_ID, 1, expected_version=1, checked=False)


async def test_update_todo_item_retries_once_on_conflict(make_entity: EntityFactory) -> None:
    client = AsyncMock()
    client.update_item.side_effect = [
        EveryListConflictError(_milk(version=5)),
        _milk(version=6, checked=True),
    ]
    client.get_items.return_value = [_milk(version=6, checked=True)]
    entity = make_entity(client, [_milk()])

    await entity.async_update_todo_item(
        TodoItem(uid="1", summary="Milk", status=TodoItemStatus.COMPLETED)
    )

    assert client.update_item.await_count == 2
    second_call = client.update_item.await_args_list[1]
    assert second_call.kwargs["expected_version"] == 5


async def test_delete_todo_items_success(make_entity: EntityFactory) -> None:
    client = AsyncMock()
    client.delete_item.return_value = None
    client.get_items.return_value = []
    entity = make_entity(client, [_milk()])

    await entity.async_delete_todo_items(["1"])

    client.delete_item.assert_awaited_once_with(LIST_ID, 1, expected_version=1)


async def test_delete_todo_items_retries_once_on_conflict(make_entity: EntityFactory) -> None:
    client = AsyncMock()
    client.delete_item.side_effect = [EveryListConflictError(_milk(version=9)), None]
    client.get_items.return_value = []
    entity = make_entity(client, [_milk()])

    await entity.async_delete_todo_items(["1"])

    assert client.delete_item.await_count == 2
    second_call = client.delete_item.await_args_list[1]
    assert second_call.kwargs["expected_version"] == 9


async def test_move_todo_item_to_front(make_entity: EntityFactory) -> None:
    client = AsyncMock()
    item1 = _milk(item_id=1, name="Milk", sort_order=0)
    item2 = _milk(item_id=2, name="Eggs", sort_order=1)
    client.move_item.return_value = _milk(item_id=2, name="Eggs", sort_order=0)
    client.get_items.return_value = [item2, item1]
    entity = make_entity(client, [item1, item2])

    await entity.async_move_todo_item(uid="2", previous_uid=None)

    client.move_item.assert_awaited_once_with(LIST_ID, 2, previous_item_id=None, expected_version=1)


async def test_move_todo_item_after_previous(make_entity: EntityFactory) -> None:
    client = AsyncMock()
    item1 = _milk(item_id=1, name="Milk", sort_order=0)
    item2 = _milk(item_id=2, name="Eggs", sort_order=1)
    client.move_item.return_value = _milk(item_id=1, name="Milk", sort_order=1)
    client.get_items.return_value = [item2, item1]
    entity = make_entity(client, [item1, item2])

    await entity.async_move_todo_item(uid="1", previous_uid="2")

    client.move_item.assert_awaited_once_with(LIST_ID, 1, previous_item_id=2, expected_version=1)


async def test_move_todo_item_unknown_uid_raises(make_entity: EntityFactory) -> None:
    entity = make_entity(AsyncMock(), [_milk()])

    with pytest.raises(ValueError, match="No item 999"):
        await entity.async_move_todo_item(uid="999")


async def test_move_todo_item_unknown_previous_uid_raises(make_entity: EntityFactory) -> None:
    entity = make_entity(AsyncMock(), [_milk()])

    with pytest.raises(ValueError, match="No item 999"):
        await entity.async_move_todo_item(uid="1", previous_uid="999")


async def test_move_todo_item_retries_once_on_conflict(make_entity: EntityFactory) -> None:
    client = AsyncMock()
    item_a = _milk(item_id=1, name="A", sort_order=0)
    item_c = _milk(item_id=3, name="C", sort_order=2)
    client.move_item.side_effect = [
        EveryListConflictError(_milk(item_id=3, name="C", version=9)),
        _milk(item_id=3, name="C", sort_order=1),
    ]
    client.get_items.return_value = [item_a, _milk(item_id=3, name="C", sort_order=1)]
    entity = make_entity(client, [item_a, item_c])

    await entity.async_move_todo_item(uid="3", previous_uid="1")

    assert client.move_item.await_count == 2
    first_call, retry_call = client.move_item.await_args_list
    assert first_call.args == (LIST_ID, 3)
    assert first_call.kwargs == {"previous_item_id": 1, "expected_version": 1}
    assert retry_call.args == (LIST_ID, 3)
    assert retry_call.kwargs == {"previous_item_id": 1, "expected_version": 9}


async def test_async_setup_entry_creates_one_entity_per_list(hass: HomeAssistant) -> None:
    client = AsyncMock()
    coordinator = EveryListCoordinator(hass, client, [3, 5])
    coordinator.data = {3: [], 5: []}
    entry = MockConfigEntry(
        domain="everylist",
        data={
            CONF_LIST_IDS: {
                "3": {"name": "Groceries", "role": "editor"},
                "5": {"name": "Hardware", "role": "viewer"},
            }
        },
    )
    entry.runtime_data = EveryListRuntimeData(client=client, coordinator=coordinator)

    added: list[EveryListTodoListEntity] = []
    await async_setup_entry(hass, entry, lambda entities: added.extend(entities))
    await coordinator.async_shutdown()

    by_name = {entity.name: entity for entity in added}
    assert set(by_name) == {"Groceries", "Hardware"}
    assert by_name["Groceries"].supported_features != TodoListEntityFeature(0)
    assert by_name["Hardware"].supported_features == TodoListEntityFeature(0)


def test_to_todo_item_carries_notes_as_description() -> None:
    item = EveryListItem.from_json(item_json(notes="brand: oat milk"))
    todo_item = _to_todo_item(item)
    assert todo_item.description == "brand: oat milk"
