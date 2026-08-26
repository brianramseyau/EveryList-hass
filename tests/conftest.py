"""Shared fixtures for the EveryList test suite."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.everylist.const import CONF_LIST_IDS, DOMAIN

pytest_plugins = "pytest_homeassistant_custom_component"

BASE_URL = "https://everylist.example.com"
TOKEN = "elt_test_token"
LIST_ID = 3
LIST_NAME = "Groceries"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> Generator[None]:
    """Make ``custom_components.everylist`` loadable by HA's component loader."""
    yield


def item_json(
    *,
    item_id: int = 1,
    list_id: int = LIST_ID,
    name: str = "Milk",
    checked: bool = False,
    version: int = 1,
    notes: str | None = None,
    sort_order: int = 0,
) -> dict:
    """Build an item payload shaped like the real API's ItemTransformer output."""
    return {
        "id": item_id,
        "listId": list_id,
        "name": name,
        "quantity": None,
        "notes": notes,
        "categoryId": None,
        "storeId": None,
        "price": None,
        "checked": checked,
        "checkedAt": None,
        "sortOrder": sort_order,
        "createdBy": 1,
        "createdAt": "2026-01-01T00:00:00.000+00:00",
        "updatedAt": "2026-01-01T00:00:00.000+00:00",
        "deletedAt": None,
        "version": version,
    }


def list_json(*, list_id: int = LIST_ID, name: str = LIST_NAME, icon: str | None = None) -> dict:
    """Build a list payload shaped like the real API's ListTransformer output."""
    return {
        "id": list_id,
        "name": name,
        "color": None,
        "icon": icon,
        "ownerId": 1,
        "folderId": None,
        "archived": False,
        "badgeExcluded": False,
        "useCategories": True,
        "passcodeHash": None,
        "createdAt": "2026-01-01T00:00:00.000+00:00",
        "updatedAt": "2026-01-01T00:00:00.000+00:00",
        "version": 1,
        "itemCount": 0,
        "role": "editor",
        "memberCount": 1,
        "ownerName": "Test User",
    }


def token_me_json(*, grants: list[dict] | None = None) -> dict:
    """Build a ``GET /tokens/me`` payload shaped like the real API's response."""
    return {
        "id": 1,
        "name": "Home Assistant",
        "grants": grants if grants is not None else [{"listId": LIST_ID, "role": "editor"}],
        "lastUsedAt": None,
        "expiresAt": None,
        "createdAt": "2026-01-01T00:00:00.000+00:00",
    }


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"EveryList ({LIST_NAME})",
        unique_id=BASE_URL,
        data={
            "url": BASE_URL,
            "access_token": TOKEN,
            CONF_LIST_IDS: {str(LIST_ID): {"name": LIST_NAME, "role": "editor", "icon": None}},
        },
    )
