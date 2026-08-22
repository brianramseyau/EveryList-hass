"""Constants for the EveryList integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "everylist"

CONF_LIST_IDS: Final = "list_ids"
"""Config-entry data key: ``{"<list id>": "<list name>", ...}`` for every exposed list."""

CONF_LIST_IDS_INPUT: Final = "list_ids_csv"
"""Config-flow form field: a comma-separated string of list IDs, before validation."""

API_PREFIX: Final = "/api/v1"

DEFAULT_SCAN_INTERVAL_SECONDS: Final = 30
