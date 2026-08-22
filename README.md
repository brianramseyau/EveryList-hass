<p align="center">
  <img src="https://raw.githubusercontent.com/brianramseyau/EveryList/main/branding/icon-192.png" width="96" height="96" alt="EveryList icon">
</p>

<h1 align="center">EveryList for Home Assistant</h1>

<p align="center">
  A HACS integration that exposes your <a href="https://github.com/brianramseyau/EveryList">EveryList</a> shopping lists as native Home Assistant <code>todo.*</code> entities — so Voice Assist can add and check off items with zero custom NLU.
</p>

<p align="center">
  <a href="https://github.com/brianramseyau/everylist-hass/actions/workflows/validate.yml"><img alt="Validate" src="https://github.com/brianramseyau/everylist-hass/actions/workflows/validate.yml/badge.svg"></a>
  <a href="https://github.com/brianramseyau/everylist-hass/actions/workflows/test.yml"><img alt="Test" src="https://github.com/brianramseyau/everylist-hass/actions/workflows/test.yml/badge.svg"></a>
  <a href="https://github.com/hacs/integration"><img alt="hacs" src="https://img.shields.io/badge/HACS-Custom-41BDF5.svg"></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-green"></a>
</p>

---

## What this does

Each EveryList list you choose to expose becomes a `todo.*` entity in Home Assistant. Home
Assistant's `todo` domain already understands add/complete voice intents out of the box, so
"add milk to the shopping list" and "mark milk as done" work the moment the entity exists — no
custom sentences or intent scripts required.

- **Reads** your list's items (`todo.groceries` shows exactly what's on the EveryList list).
- **Adds** items via Voice Assist or the Lovelace to-do card, fuzzy-matching near-miss
  transcriptions ("miilk") against the list's recent item names before creating anything new.
- **Completes / renames / deletes** items, both ways — items added from the EveryList app or by
  another household member show up here too (on the next poll; see [Limitations](#limitations)).

See [`foundational/PLAN.md`](foundational/PLAN.md) for the full design — API contract, the
optimistic-locking/conflict-retry behavior, and the reasoning behind each decision below.

## Requirements

- A running [EveryList](https://github.com/brianramseyau/EveryList) instance, reachable from
  Home Assistant, with a real (CA-trusted or otherwise HA-trusted) HTTPS endpoint.
- A **Personal Access Token (PAT)**, minted from EveryList's `Settings → Access Tokens`, scoped
  to the list(s) you want to expose. This integration only ever authenticates as a PAT — it has
  no part in minting or rotating one. Personal Access Tokens require a reasonably recent
  EveryList version; if `Settings → Access Tokens` doesn't exist yet, update EveryList first.
- Home Assistant 2024.12 or newer.

## Installation

### Via HACS (recommended)

1. HACS → the "⋮" menu (top right) → **Custom repositories**.
2. Add `https://github.com/brianramseyau/everylist-hass`, category **Integration**.
3. Find **EveryList** in HACS and install it, then restart Home Assistant.

### Manual

Copy `custom_components/everylist` into your Home Assistant `config/custom_components/`
directory and restart Home Assistant.

## Configuration

Settings → Devices & Services → Add Integration → **EveryList**. You'll be asked for:

| Field | What to enter |
|---|---|
| Base URL | Your EveryList instance's base URL, e.g. `https://everylist.example.com` |
| Personal Access Token | The `elt_...` token from `Settings → Access Tokens` |

That's it — the integration calls `GET /tokens/me` to discover exactly which lists the token
was scoped to (and at what role) when you minted it, so you never re-enter list IDs by hand. A
list you were granted `viewer` on still shows up as a `todo.*` entity, just read-only (no
add/complete/delete) — the API would reject a write from that token anyway, so this integration
doesn't offer controls that would only fail.

If the token is revoked or expires, Home Assistant prompts you to reauthenticate. That's also
how you change which lists this entry exposes later: mint a new token scoped to whatever set of
lists you want and reauthenticate with it — the entry's list set is re-discovered fresh from the
new token rather than staying pinned to the old one.

## Limitations

- **Polling, not push.** This first release polls every 30 seconds rather than subscribing to
  EveryList's realtime channel — a change made outside Home Assistant can take up to 30 seconds
  to appear here. Voice Assist's own writes still apply immediately (they don't wait on the
  poll). Live push is a tracked follow-up; see `foundational/PLAN.md`.
- A PAT is capped at `editor` — this integration can never do anything an owner-only action
  (like deleting the list itself) would require, by design.

## Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements_test.txt

ruff format custom_components tests
ruff check custom_components tests

pytest tests --cov=custom_components.everylist --cov-branch --cov-report=term-missing
```

The test suite mirrors the main EveryList repo's own bar: `pytest-homeassistant-custom-component`
for a real (in-memory) Home Assistant instance per test, and a 100%-branch coverage gate
(`pyproject.toml`'s `[tool.coverage.report]`) enforced both locally and in CI
(`.github/workflows/test.yml`). `.github/workflows/validate.yml` runs the HACS and
[hassfest](https://developers.home-assistant.io/blog/2020/04/16/hassfest) checks required for
HACS publishing on every push.

## License

[MIT](LICENSE)
