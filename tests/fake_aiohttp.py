"""A minimal aiohttp.ClientSession stand-in for tests.

Replaces ``aioresponses`` (whose response-class shimming breaks against
current aiohttp releases) with a hand-rolled fake that only implements the
`async with session.request(...) as resp:` shape ``api.py`` actually uses.
"""

from __future__ import annotations

from typing import Any

import aiohttp
from yarl import URL

_FAKE_REQUEST_INFO = aiohttp.RequestInfo(
    url=URL("http://mock"), method="GET", headers={}, real_url=URL("http://mock")
)


class FakeResponse:
    def __init__(self, *, status: int = 200, json_body: Any = None) -> None:
        self.status = status
        self._json_body = json_body

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def json(self) -> Any:
        return self._json_body

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise aiohttp.ClientResponseError(
                request_info=_FAKE_REQUEST_INFO, history=(), status=self.status
            )


class FakeSession:
    """Routes ``request(method, url, ...)`` to a canned response or exception, by URL."""

    def __init__(self) -> None:
        self._responses: dict[tuple[str, str], FakeResponse | Exception] = {}
        self.calls: list[dict[str, Any]] = []

    def add_response(
        self, method: str, url: str, *, status: int = 200, json_body: Any = None
    ) -> None:
        self._responses[(method.upper(), url)] = FakeResponse(status=status, json_body=json_body)

    def add_exception(self, method: str, url: str, exc: Exception) -> None:
        self._responses[(method.upper(), url)] = exc

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": method, "url": str(url), **kwargs})
        key = (method.upper(), str(url))
        outcome = self._responses.get(key)
        if outcome is None:
            raise AssertionError(f"FakeSession: no mocked response for {key}")
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
