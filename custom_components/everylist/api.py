"""Thin async client for the EveryList REST API.

Tracks the contract implemented by EveryList's ``apps/api`` exactly (routes,
request/response shapes, the ``{"data": ...}`` envelope, and the
optimistic-locking ``expectedVersion``/409 pattern) rather than inventing its
own — see ``foundational/PLAN.md`` for the endpoints this integration uses and
why.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import aiohttp

from .const import API_PREFIX


class EveryListError(Exception):
    """Base error for all EveryList API failures."""


class EveryListAuthError(EveryListError):
    """The token was rejected, or has no grant on the requested list.

    A list the token isn't scoped to 404s rather than 403s (EveryList's
    `ListPolicy` masks "not authorized" as "not found" so a token can't probe
    for lists it doesn't have), so this is raised for both status codes —
    either way the integration can't proceed without the user fixing the
    token or its configured list IDs.
    """


class EveryListConnectionError(EveryListError):
    """The API could not be reached at all (network error, bad base URL, ...)."""


class EveryListConflictError(EveryListError):
    """A write's ``expectedVersion`` was stale; carries the server's current item."""

    def __init__(self, item: EveryListItem) -> None:
        super().__init__(f"version conflict on item {item.id}")
        self.item = item


@dataclass(slots=True, kw_only=True)
class EveryListItem:
    """A single list item, as returned by the items endpoints."""

    id: int
    list_id: int
    name: str
    checked: bool
    version: int
    notes: str | None = None

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> EveryListItem:
        return cls(
            id=data["id"],
            list_id=data["listId"],
            name=data["name"],
            checked=data["checked"],
            version=data["version"],
            notes=data.get("notes"),
        )


@dataclass(slots=True, kw_only=True)
class EveryListList:
    """A list's identity, as returned by ``GET /lists/:id``."""

    id: int
    name: str

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> EveryListList:
        return cls(id=data["id"], name=data["name"])


@dataclass(slots=True, kw_only=True)
class EveryListGrant:
    """One list a PAT is scoped to, as reported by ``GET /tokens/me``."""

    list_id: int
    role: str

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> EveryListGrant:
        return cls(list_id=data["listId"], role=data["role"])


class EveryListClient:
    """Minimal async wrapper around the EveryList REST API used by this integration."""

    def __init__(self, session: aiohttp.ClientSession, base_url: str, token: str) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._token = token

    async def _get(self, path: str, *, params: dict[str, str] | None = None) -> Any:
        return await self._call("GET", path, params=params)

    async def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        # A 5xx from raise_for_status() is a ClientResponseError, a ClientError
        # subclass — caught below and folded into EveryListConnectionError
        # along with real network failures, since callers only need to tell
        # "can't act as configured" (EveryListAuthError) apart from
        # "temporarily unreachable" (EveryListConnectionError).
        url = f"{self._base_url}{API_PREFIX}{path}"
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            async with self._session.request(method, url, headers=headers, **kwargs) as resp:
                if resp.status in (401, 403, 404):
                    raise EveryListAuthError(f"{method} {path} returned {resp.status}")
                if resp.status == 409:
                    # Only PATCH/DELETE on an item can 409 (a stale
                    # expectedVersion) — the body carries the server's
                    # current version for the caller to inspect and retry.
                    return await resp.json()
                resp.raise_for_status()
                if resp.status == 204:
                    return None
                return await resp.json()
        except aiohttp.ClientError as err:
            raise EveryListConnectionError(str(err)) from err

    async def get_list(self, list_id: int) -> EveryListList:
        """Fetch a list's identity — also the config-flow validation call for scope+reachability."""
        body = await self._get(f"/lists/{list_id}")
        return EveryListList.from_json(body["data"])

    async def get_my_grants(self) -> list[EveryListGrant]:
        """The authenticating PAT's own list grants — the config-flow list-discovery call."""
        body = await self._get("/tokens/me")
        return [EveryListGrant.from_json(grant) for grant in body["data"]["grants"]]

    async def get_items(self, list_id: int, *, include_checked: bool = True) -> list[EveryListItem]:
        params = {"includeChecked": "true" if include_checked else "false"}
        body = await self._get(f"/lists/{list_id}/items", params=params)
        return [EveryListItem.from_json(item) for item in body["data"]]

    async def get_recent_names(self, list_id: int) -> list[str]:
        body = await self._get(f"/lists/{list_id}/items/recent-names")
        return list(body["data"])

    async def create_item(self, list_id: int, name: str) -> EveryListItem:
        body = await self._call("POST", f"/lists/{list_id}/items", json={"name": name})
        return EveryListItem.from_json(body["data"])

    async def update_item(
        self, list_id: int, item_id: int, *, expected_version: int, **fields: Any
    ) -> EveryListItem:
        """Raises :class:`EveryListConflictError` (carrying the server's current item) on a 409."""
        payload: dict[str, Any] = {**fields, "expectedVersion": expected_version}
        body = await self._call("PATCH", f"/lists/{list_id}/items/{item_id}", json=payload)
        item = EveryListItem.from_json(body["data"])
        if body.get("conflict"):
            raise EveryListConflictError(item)
        return item

    async def delete_item(self, list_id: int, item_id: int, *, expected_version: int) -> None:
        """Raises :class:`EveryListConflictError` (carrying the server's current item) on a 409."""
        body = await self._call(
            "DELETE",
            f"/lists/{list_id}/items/{item_id}",
            json={"expectedVersion": expected_version},
        )
        if body is not None and body.get("conflict"):
            raise EveryListConflictError(EveryListItem.from_json(body["data"]))
