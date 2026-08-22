"""Tests for the thin EveryList REST client."""

from __future__ import annotations

import aiohttp
import pytest

from custom_components.everylist.api import (
    EveryListAuthError,
    EveryListClient,
    EveryListConflictError,
    EveryListConnectionError,
)

from .conftest import BASE_URL, LIST_ID, TOKEN, item_json, list_json
from .fake_aiohttp import FakeSession

ITEMS_URL = f"{BASE_URL}/api/v1/lists/{LIST_ID}/items"
LIST_URL = f"{BASE_URL}/api/v1/lists/{LIST_ID}"


@pytest.fixture
def session() -> FakeSession:
    return FakeSession()


@pytest.fixture
def client(session: FakeSession) -> EveryListClient:
    return EveryListClient(session, BASE_URL, TOKEN)


async def test_get_list(client: EveryListClient, session: FakeSession) -> None:
    session.add_response("GET", LIST_URL, json_body={"data": list_json()})

    result = await client.get_list(LIST_ID)

    assert result.id == LIST_ID
    assert result.name == "Groceries"
    assert session.calls[0]["headers"]["Authorization"] == f"Bearer {TOKEN}"


async def test_get_items_includes_checked_by_default(
    client: EveryListClient, session: FakeSession
) -> None:
    session.add_response(
        "GET",
        f"{ITEMS_URL}",
        json_body={"data": [item_json(item_id=1), item_json(item_id=2, checked=True)]},
    )

    items = await client.get_items(LIST_ID)

    assert [item.id for item in items] == [1, 2]
    assert items[1].checked is True
    assert session.calls[0]["params"] == {"includeChecked": "true"}


async def test_get_items_excludes_checked(client: EveryListClient, session: FakeSession) -> None:
    session.add_response("GET", ITEMS_URL, json_body={"data": [item_json(item_id=1)]})

    items = await client.get_items(LIST_ID, include_checked=False)

    assert len(items) == 1
    assert session.calls[0]["params"] == {"includeChecked": "false"}


async def test_get_recent_names(client: EveryListClient, session: FakeSession) -> None:
    session.add_response("GET", f"{ITEMS_URL}/recent-names", json_body={"data": ["Milk", "Eggs"]})

    names = await client.get_recent_names(LIST_ID)

    assert names == ["Milk", "Eggs"]


async def test_create_item(client: EveryListClient, session: FakeSession) -> None:
    session.add_response("POST", ITEMS_URL, json_body={"data": item_json(name="Milk")})

    item = await client.create_item(LIST_ID, "Milk")

    assert item.name == "Milk"


async def test_update_item_success(client: EveryListClient, session: FakeSession) -> None:
    session.add_response(
        "PATCH",
        f"{ITEMS_URL}/1",
        json_body={"data": item_json(item_id=1, checked=True, version=2)},
    )

    item = await client.update_item(LIST_ID, 1, expected_version=1, checked=True)

    assert item.checked is True
    assert item.version == 2


async def test_update_item_conflict_raises_with_current_item(
    client: EveryListClient, session: FakeSession
) -> None:
    session.add_response(
        "PATCH",
        f"{ITEMS_URL}/1",
        status=409,
        json_body={"data": item_json(item_id=1, version=5), "conflict": True},
    )

    with pytest.raises(EveryListConflictError) as exc_info:
        await client.update_item(LIST_ID, 1, expected_version=1, checked=True)

    assert exc_info.value.item.version == 5


async def test_delete_item_success(client: EveryListClient, session: FakeSession) -> None:
    session.add_response("DELETE", f"{ITEMS_URL}/1", status=204)

    result = await client.delete_item(LIST_ID, 1, expected_version=1)

    assert result is None


async def test_delete_item_conflict_raises_with_current_item(
    client: EveryListClient, session: FakeSession
) -> None:
    session.add_response(
        "DELETE",
        f"{ITEMS_URL}/1",
        status=409,
        json_body={"data": item_json(item_id=1, version=7), "conflict": True},
    )

    with pytest.raises(EveryListConflictError) as exc_info:
        await client.delete_item(LIST_ID, 1, expected_version=1)

    assert exc_info.value.item.version == 7


@pytest.mark.parametrize("status", [401, 403, 404])
async def test_auth_error_on_401_403_404(
    client: EveryListClient, session: FakeSession, status: int
) -> None:
    session.add_response("GET", LIST_URL, status=status)

    with pytest.raises(EveryListAuthError):
        await client.get_list(LIST_ID)


async def test_server_error_status_wrapped_as_connection_error(
    client: EveryListClient, session: FakeSession
) -> None:
    """A 5xx is treated the same as unreachable — see the deployment-model note in PLAN.md."""
    session.add_response("GET", LIST_URL, status=500)

    with pytest.raises(EveryListConnectionError):
        await client.get_list(LIST_ID)


async def test_connection_error_wrapped(client: EveryListClient, session: FakeSession) -> None:
    session.add_exception("GET", LIST_URL, aiohttp.ClientConnectionError("boom"))

    with pytest.raises(EveryListConnectionError):
        await client.get_list(LIST_ID)
