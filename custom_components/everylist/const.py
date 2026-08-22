"""Constants for the EveryList integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "everylist"

CONF_LIST_IDS: Final = "list_ids"
"""Config-entry data key: ``{"<list id>": {"name": ..., "role": "editor" | "viewer"}, ...}``,
one entry per list the PAT is scoped to, discovered via ``GET /tokens/me`` at setup/reauth time.
"""

API_PREFIX: Final = "/api/v1"

DEFAULT_SCAN_INTERVAL_SECONDS: Final = 30
