# Phase 16, Stage 1 — Home Assistant integration

> Extracted from **Phase 16 — Voice assistant integration: Personal Access Tokens, Home
> Assistant, Alexa**, the full plan for which lives in the main EveryList repo:
> [`foundational/PHASE16_PLAN.md`](https://github.com/brianramseyau/EveryList/blob/main/foundational/PHASE16_PLAN.md).
> This file carries only the parts relevant to *this* repo (the HACS integration). Stage 0
> (Personal Access Tokens, the API-side prerequisite) has already shipped in the main repo;
> Stage 2 (the Alexa skill) lives entirely in the main repo and isn't reproduced here.

## Why a separate repo

HACS requires `custom_components/<domain>/` at the repo root, one integration per repo, and
versions the integration via that repo's own GitHub releases — nesting it in the EveryList
monorepo would conflate its release tags with app releases. EveryList's main repo is already
public, which is the other HACS requirement, but that isn't the deciding factor.

## What Stage 0 already provides (context, not this repo's work)

The main repo now supports **Personal Access Tokens (PATs)**: a second token bucket
(`User.personalAccessTokens`, prefix `elt_`, no forced expiry) alongside login/session tokens,
minted from `Settings → Access Tokens` by a list owner. A PAT is scoped to one or more specific
lists with a role capped at `editor` — never `owner` — encoded as `list:<id>:editor` /
`list:<id>:viewer` ability strings. `ListPolicy` (and the Transmit SSE channel authorizer)
intersect a PAT's encoded grants with the user's real membership on every request: a token
un-scoped to a list gets a 404 on it, indistinguishable from "list doesn't exist" — a security
property this integration must not paper over (see [Error handling](#error-handling) below).

This integration authenticates purely as a bearer PAT — it has no part in minting or rotating
tokens. A user pastes an already-minted `elt_...` token into the config flow.

## Goal

Expose each EveryList list the configured PAT is scoped to as a native `todo.*` entity via
Home Assistant's `TodoListEntity`. HA's Voice Assist already understands todo-domain
add/complete intents out of the box, so this needs no custom NLU — "add milk to shopping list"
and "mark milk as done" work the moment the entity exists.

## Design

```
custom_components/everylist/
  __init__.py       entry setup/unload, coordinator wiring
  manifest.json      domain "everylist"
  config_flow.py     prompts for base URL + PAT, discovers its list grants via a real API call
  coordinator.py      DataUpdateCoordinator: poll + push-driven refresh
  todo.py             TodoListEntity implementation (one entity per configured list)
  api.py               thin aiohttp client
  const.py
tests/                pytest + pytest-homeassistant-custom-component, 100% coverage
.github/workflows/     hassfest + HACS validation + lint/test CI
hacs.json
```

This repo holds itself to the same bar as the main repo, not a lighter one: a coverage-gated
pytest suite (mirroring `apps/api`'s `c8` 100%-branch philosophy) and CI that runs lint + tests
on every PR, set up alongside the integration code, not as an afterthought once tests already
exist.

### API surface used (all under `{base_url}/api/v1`, `Authorization: Bearer <PAT>`)

- `GET /tokens/me` (PAT-only guard — a login session has no per-list grant to report) — the
  config-flow list-discovery call, added specifically for this integration (main repo commit
  `03fa702`, found missing while building this exact flow — see git history there). Returns the
  authenticating token's own `{listId, role}` grants, so the user never re-enters list IDs by
  hand; `role` also drives whether the resulting entity is writable (`editor`) or read-only
  (`viewer`).
- `GET /lists/:listId` — called once per discovered grant to get the list's real name/color for
  the entity, and doubles as a scope re-check; a PAT unscoped to the list 404s here (shouldn't
  happen right after `/tokens/me` reported the grant, except a list deleted in between), surfaced
  as a form error rather than a generic failure.
- `GET /lists/:listId/items?includeChecked=true` → `async_get_todo_items`.
- `POST /lists/:listId/items` (`{name, ...}`) → `async_create_todo_item`, fuzzy-matched first
  against `GET /lists/:listId/items/recent-names` (`difflib.get_close_matches`, stdlib, no new
  dependency) to catch near-miss transcriptions ("miilk" vs "milk") before creating — the API's
  own dedup is an exact `LOWER(TRIM(name))` match and only catches exact repeats.
- `PATCH /lists/:listId/items/:itemId` (`{checked}` or other fields, `expectedVersion`) →
  `async_update_todo_item`.
- `DELETE /lists/:listId/items/:itemId` → `async_delete_todo_item`.
- All mutating endpoints honor the API's optimistic-lock pattern: every item carries a
  `version`; a write sent with a stale `expectedVersion` 409s with the current row instead of
  applying. On a 409 the client refetches and retries once rather than surfacing a raw error to
  Voice Assist.

Every response is wrapped as `{"data": ...}` by the API's serializer; list/item shapes and
route paths are implemented in `api.py` exactly as the main repo's
`apps/api/app/controllers/items_controller.ts` and `apps/api/start/routes.ts` define them —
this integration tracks that contract, it doesn't invent its own.

### Realtime vs. polling

The main repo's Stage 1 note describes subscribing to Transmit's SSE channel
(`__transmit/subscribe` on `list/{listId}`) for push updates, with a periodic poll as a
fallback. This repo's first cut uses `DataUpdateCoordinator` with a poll interval as the
baseline (simple, testable, matches HA's standard integration pattern) — SSE push is a
follow-up, not a blocker for a usable first release, since Voice Assist's own writes already
update the entity immediately without waiting on a poll.

### Auth and reauth

Config flow asks for base URL + PAT only; the list set is discovered from the token itself (see
above) rather than typed in. A 401 (revoked/expired token) or a 404 on a previously-working list
(scope revoked) during a coordinator update raises `ConfigEntryAuthFailed`, triggering HA's
reauth flow rather than leaving the entity silently broken. Reauth doubles as the mechanism for
changing which lists are exposed: since the list set is re-discovered from whatever the
newly-entered token grants, minting a differently-scoped PAT and reauthenticating with it updates
the entry's entities to match — no separate "reconfigure lists" flow needed.

## Sequencing

Hard dependency on Stage 0 (already shipped in the main repo). No dependency on Stage 2 (Alexa)
— ships and is usable standalone.

## Verification

- `pytest` + `pytest-homeassistant-custom-component` with `pytest-cov` enforcing 100% branch
  coverage, run via this repo's own `.github/workflows/` on every PR.
- Manual end-to-end: add this checkout as a custom HACS repository against a scratch HA
  instance, pointed at a throwaway local EveryList dev DB. Confirm: "add milk" creates an item,
  "mark milk as done" completes it, an item added from the phone app shows up in HA on the next
  poll.
- First real rollout against prod: mint a fresh, single-list PAT specifically for this, so a
  bug in the integration can only affect that one list, and confirm revoking it from
  `/settings/tokens` actually kills HA's access before trusting it unattended.
