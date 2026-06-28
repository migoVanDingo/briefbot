# 0022 — Expose the consumer API for `trader`

**Status:** ✅ Implemented (2026-06-22, code) — consumer data routes moved under
`/consumer`; `test_api.py` updated; 157 pytest pass. **nginx location block is a
server-side step** (documented in `devops.md`, not yet applied on the VM).
**Phase:** Build/Ops · **Depends on:** 0003 (consumer API), the prod deploy (0-CICD).
**Sibling:** [0020 scheduling](./0020-topic-scheduling-config.md) (keeps `crypto` hot
→ this is how `trader` actually pulls it).

## Implementation notes

- `api.py`: `/topics` + `/items` now on an `APIRouter(prefix="/consumer")`;
  root `/health` unchanged (deploy check). Auth/scoping/rate-limit untouched.
- **Remaining server step:** add `location /consumer/ { proxy_pass … }` to the VM
  nginx site + reload, then point `trader` at `…/consumer` with a scoped token
  (exact block in `devops.md`). No code redeploy needed for the nginx change.

The read-only **consumer API** (`/topics`, `/items` — service-token auth, built in
0003) exists but **isn't reachable in prod**: nginx serves the SPA at `/` and only
proxies `/api`, so the consumer routes collide with SPA paths and 404. Expose them
on a **distinct, non-colliding prefix** so `trader` can pull fresh stories (esp.
`crypto`, every 15 min once 0020 lands).

## The problem (concrete)

- `bbv2.api.create_app` mounts the consumer routes at **root**: `GET /health`,
  `/topics`, `/items` (`api.py`). `add_dashboard_routes` adds `/api/*` to the same
  app (`cli.py: cmd_serve`).
- In prod, **nginx** (`:8081`) serves the built dashboard for `/` and proxies only
  `/api` to the backend (`:8080`). So `/topics` hits the SPA, not the API.
- We can't just proxy `/topics` — it (and any future SPA route) would collide.

## Decision

Give the **consumer data routes their own prefix** and proxy just that:

- Keep **`GET /health`** at root (liveness — the **deploy health check** curls
  `127.0.0.1:8080/health` directly; don't move it).
- Mount the consumer data routes under **`/consumer`** → `GET /consumer/topics`,
  `GET /consumer/items`. nginx proxies **`location /consumer/`** to the backend.
- `trader` points its base URL at `https://briefbot.tailb058fe.ts.net/consumer`.

Service-token auth, scoping, and per-token rate limit are **unchanged** (0003/0016);
nginx forwards the `Authorization` header.

## What this is NOT

- **Not** a new auth model — the existing `bbv2 token create/list/revoke` service
  tokens still gate it.
- **Not** dashboard/session auth — this path never touches Firebase/cookies.
- **Not** a public endpoint — still tailnet-only behind `tailscale serve`.

## Phase 1 — Prefix the consumer routes

1.1 In `api.py`, move `/topics` + `/items` onto an `APIRouter(prefix="/consumer")`
    (keep `/health` at root). `require_scope` dependency unchanged. Update the
    in-code docstring/paths.
1.2 Update `tests/test_api.py` to the new paths (`/consumer/topics`,
    `/consumer/items`); `/health` test stays at root.

## Phase 2 — nginx + serving

2.1 Add an nginx `location /consumer/ { proxy_pass http://127.0.0.1:8080; ... }`
    (mirror the `/api` proxy block: forward `Authorization`, `Host`, timeouts).
    `/consumer` must be matched **before** the SPA `try_files` catch-all.
2.2 Confirm `tailscale serve` still fronts it (same origin/port) — no extra config;
    `/consumer/*` rides the existing HTTPS front.
2.3 Document the nginx block in `_documentation/devops.md` (it's part of the
    server config preserved outside the repo — note the exact `location`).

## Phase 3 — Consumer ergonomics (small)

3.1 `/consumer/items` already returns `next_since` (checkpoint cursor) — confirm
    `trader` uses it for incremental pulls; document the contract
    (`?topic=&since=&limit=`, ascending `fetched_at`, checkpoint on `next_since`).
3.2 Optional: a `GET /consumer/health` alias (token-free) if `trader` wants a
    scoped liveness probe distinct from the deploy's root `/health`.

## Phase 4 — Verify + docs

4.1 `pytest tests/test_api.py` green on the new paths; full suite green.
4.2 Manual prod check (tailnet): `curl -H "Authorization: Bearer <token>"
    https://briefbot.tailb058fe.ts.net/consumer/topics` → scoped topics.
4.3 Update `architecture.md` (consumer API now at `/consumer`), `README.md`,
    `CLAUDE.md` (the "not yet proxied" caveat → done), `roadmap.md`. Hand `trader`
    the base URL + a scoped token (`bbv2 token create --label trader --topics
    crypto,markets,…`).

## Done when

`trader` can `GET https://briefbot.tailb058fe.ts.net/consumer/items?topic=crypto&
since=<cursor>` with its service token and get the newest crypto stories, pulling
incrementally via `next_since` — with the SPA, dashboard API, and deploy health
check all still working.

## Note / sequencing

Pairs with **0020**: 0020 keeps `crypto` fresh (15-min collection), 0022 is the
pipe that hands it to `trader`. Either order works; do 0022 whenever the `trader`
data-platform work (`../trader/_plans/0017`) is ready to consume.
