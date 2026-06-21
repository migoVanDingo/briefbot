# 0016 — Tech Debt + Security Hardening

**Status:** ✅ Done — **Date:** 2026-06-21 — all 5 phases shipped; 135 pytest +
dashboard `tsc`/build green; `/code-review` (high) run, its 2 confirmed bugs
(streamed-conn-on-retry leak, no-Location redirect) fixed.

Consolidates the existing roadmap tech-debt/known-bugs with a fresh three-pass
audit (security · backend correctness · frontend). Goal: clear the genuine
issues before the Tailscale family deploy, fix the known bugs, and bring the one
over-cap file back under 600. No feature work.

## Audit summary

The codebase is fundamentally sound: parameterized SQL throughout (no injection),
no `dangerouslySetInnerHTML`/raw-HTML render (no XSS), Firebase-verified dashboard
auth, consistent owner-only admin gating, no IDOR, secrets gitignored. Real work
clusters into SSRF, the deploy posture, a few correctness bugs, and known debt.

**Deliberately NOT doing (accepted at personal scale, documented in roadmap):**
consumer-token *hashing* (token is PK+FK and a live trader token exists — risky
migration, marginal gain); in-memory rate limiter being single-process;
per-statement autocommit; near-cap Python file splits (none over 600).

## Phase 1 — Security hardening

1.1 **SSRF guard** (HIGH, NEW reach). `agent._fetch_text` is driven by the
    `summarize_article` chat tool → any logged-in user can make the server GET an
    arbitrary URL (incl. `169.254.169.254`, loopback, RFC-1918). Redirects are
    followed unchecked, bypassing any allowlist. Fix: new `bbv2/safefetch.py`
    with `safe_get()` — reject non-http(s) schemes; resolve host and block
    loopback/link-local/private/ULA/multicast/reserved IPs; `allow_redirects=False`
    + manual per-hop re-validation; stream with a byte cap (response-size DoS).
    Route `agent._fetch_text`, `fetch.fetch_rss_feed`, `discover.discover_site_feeds`
    through it. Escape hatch `BBV2_ALLOW_PRIVATE_FETCH=true` for dev. Tests.
1.2 **CORS + bind env-driven** (MEDIUM, known — blocks Tailscale). `config.allowed_origins()`
    from `ALLOWED_ORIGINS` (csv; default `localhost:5180`,`127.0.0.1:5180`);
    `--host` honors `BBV2_SERVE_HOST`. Keep explicit allowlist (never `*` with
    `allow_credentials=True`).
1.3 **Drop `verify_ssl=false` source override** (LOW, NEW). `fetch.py` always
    verifies TLS — remove the per-source escape hatch.
1.4 **Consumer-token revoke + scope validation** (MEDIUM, NEW). Add `revoked_at`
    column + `revoke_token()`; auth rejects revoked tokens; `bbv2 token revoke
    <label|token>` CLI. Reject empty `--topics` at creation (valid-yet-useless
    token). Hashing deferred (see above).

## Phase 2 — Backend correctness

2.1 **Stale-items recency filter + newest-first sort** (MEDIUM, known/confirmed).
    `collect.collect_source` upserts feed-order items with no cutoff, and the
    "newest-first cap" comment is wrong (feedparser order ≠ newest). Sort by
    `published_at` desc and drop items older than `BBV2_COLLECT_MAX_AGE_DAYS`
    (default 14) before the per-source cap.
2.2 **Wrap connection errors in `LLMError`** (MEDIUM, NEW). `request_with_backoff`
    re-raises raw `requests.RequestException` on exhaustion; the agent turn-loop
    only catches `LLMError`, so a network blip becomes an unhandled 500 inside the
    SSE stream. Wrap in `llm.py` so all LLM entry points raise `LLMError`.
2.3 **Meter topic-moderation LLM call** (MEDIUM, NEW — roadmap mis-attributes
    this to dead `expand_keywords`). Thread `metered_generate(store, user_id,
    "moderation")` into `moderate_topic` for both the REST (`POST /api/topics`)
    and chat-driven `create_topic` paths.
2.4 **`print()` → `logging`** (MEDIUM, known). Replace prints in
    collect/provision/scheduler/nightly with a module `logging` logger writing to
    `config.log_dir()` + console (timestamps/levels for unattended cron). CLI
    user-facing prints stay.
2.5 **Delete dead relevance keyword path** (MEDIUM, NEW). `relevance.expand_keywords`,
    `is_relevant`, `relevance_hits`, `keyword_tokens` and `store get/set_topic_keywords`
    have no production callers (superseded by the LLM quickscan). Delete + trim
    `test_relevance.py`.
2.6 **Close per-thread connections on shutdown** (LOW, NEW). Bounded leak: each
    uvicorn worker opens a connection never closed. Add a FastAPI shutdown handler
    / connection registry.
2.7 **Rate-limiter key eviction** (LOW, NEW). `ratelimit._hits` never drops empty
    deques — opportunistic prune to bound growth.

## Phase 3 — Bulk approve-all (fixes a known bug)

3.1 **Backend** `POST /api/topics/{slug}/sources/approve-all` (admin) wrapping the
    existing `store.approve_all_candidates` in one transaction.
3.2 **Frontend** `TopicDetail.approveAll` calls the bulk endpoint instead of
    `Promise.all` of N POSTs; fix the lossy error path (refresh on partial).

## Phase 4 — Frontend

4.1 **CSS split** (MEDIUM, known #1 — only over-cap file at 1130). Carve
    `index.css` into per-area files under `src/styles/` (base→responsive order),
    `index.css` becomes an `@import` barrel. Every file < 600.
4.2 **Fix `--surface2` / `--accent2` variable mismatch** (MEDIUM, NEW real visual
    bug). `theme.ts` injects `--surface-2`/`--accent-2`; CSS reads `var(--surface2)`
    in 5 places (silent transparent fallback). Align names.
4.3 **Abort SSE on unmount** (MEDIUM, NEW). Thread an `AbortController` signal into
    `api.streamSSE`; abort in a `useEffect` cleanup in `Chat.tsx` + `TopicsHome.tsx`.
4.4 **Minor** (LOW): `aria-hidden` on the Login `◆`; surface the silently-swallowed
    post-provision auto-subscribe failure (`TopicsHome`) as a soft warning.

## Phase 5 — Verify + docs

- `pytest` (offline) + `npm run build` (dashboard) green.
- `/code-review` per CLAUDE.md; address findings; re-verify.
- Update `_documentation/architecture.md` + `README.md`; prune `roadmap.md`
  (move shipped items to Done, keep accepted-by-design notes).
