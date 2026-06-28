# 0025 — Codebase review + remediation

A full review/analysis pass (security, correctness/concurrency, modularity,
frontend/mobile) across the `0018`–`0024` work. Findings below are **verified**
against the code (each agent read the source; the four highest-impact items were
re-confirmed by hand). Sorted by severity, then a phase-by-phase fix plan.

## Findings (verified)

### Critical / High

| # | Sev | Where | Issue |
|---|-----|-------|-------|
| S1 | HIGH | `auth_api.py:88` | `/api/auth/exchange` never checks Firebase `email_verified`; owner is bootstrapped on `email ∈ ADMIN_EMAILS`. If the Firebase project ever enables email/password (or any unverified-email provider), an attacker registering the owner's address gets owner. |
| C1 | HIGH | `agent.py:497-522` | Chat tool dispatch (`execute_tool`, `_create_topic_events`) is **not** exception-guarded (only `call_model` is). A `sqlite3.OperationalError` (lock) or any tool error aborts the SSE stream with no `done`/`error` event and leaves the conversation half-written (user msg saved, no assistant msg). |
| M1 | HIGH | `dashboard_api.py` (672 lines) | Over the **600-line hard cap** (CLAUDE.md). The split pattern already exists (`add_*_routes`); topic/source + brief/story routes were never extracted. |
| F1 | HIGH | `OnboardingTour.tsx` | First-run tour steps target `[data-tour=…]` anchors that live only on the desktop nav (`display:none` < 768px). On phones the whole walkthrough anchors to invisible elements. |

### Medium

| # | Sev | Where | Issue |
|---|-----|-------|-------|
| C2 | MED | `usage.py` + `agent.py:450` | Budget gate is once-per-turn; a turn loops up to `MAX_ITERATIONS=8` model calls with no mid-loop re-check → one allowed turn can overspend many times the remaining budget. |
| C3 | MED | `ratelimit.py:43-50` | `RateLimiter` is not thread-safe; sync routes run on the anyio threadpool. `_sweep` iterating `_hits` while another thread inserts a key → `RuntimeError: dictionary changed size during iteration` (500), plus under-enforcement. |
| C4 | MED | `brief.py:147-154` | `get_or_build_brief` is check-then-act; two concurrent first-views build the brief twice (double LLM spend, last-writer-wins text). |
| M2 | MED | `api.py`, `dashboard_chat.py`, `dashboard_api.py` | The exact 429 "Too many requests" HTTPException is built in 3 places; `dashboard_chat` re-implements the limiter check instead of the existing `_enforce_rate` helper. |
| M3 | MED | `dashboard_api.py:474,565` | Story-row serialization (`{**_item_dict(r), feedback_vote, is_saved}`) duplicated. |
| M4 | MED | `dashboard_api.py` (4 routes) | Four near-identical `try/except → HTTPException(400, str(exc))` wrappers around LLM calls, with inconsistent swallow-vs-surface behavior. |
| M5 | MED | `api.ts` (552 lines) | ~260 lines of `interface`/`type` mixed with the client; split into `api.types.ts`. |
| H2 | MED | `dashboard_api.py:295` + `agent.py:334` | Topic-provisioning orchestration (generator wiring + brief-window gate + `create_run` + `submit`) is copy-pasted across the two surfaces. |
| F2 | MED | `Chat.tsx`, `Favorites.tsx`, `Stories.tsx` | Uncancelled fetches set state from in-flight requests → stale content on fast switches (the `let cancelled` pattern in Headlines is the fix). |
| F3 | MED | `Headlines.tsx:131` | Topic switch fires `briefStories(newSlug, oldBrief.date)` for one render (introduced in 0025-pre headlines fix) → flash of wrong stories. |
| F4 | MED | `admin/TopicDetail.tsx:171` | `.detail-actions` (3 text buttons) has no `flex-wrap` → overflows < 480px. |
| F5 | MED | `responsive.css:20` | Mobile chat sidebar is a fixed 28vh band with no collapse — eats a third of the screen. |

### Low (batched / deferred)

- C5 `topic_image.maybe_kick` TOCTOU → double image gen (cheap conditional-UPDATE claim fixes it).
- S2 cookies default non-Secure (env sets it in prod; default to secure).
- S3 auth routes bypass the per-user limiter (IP-key the exchange).
- M6 `cli.py` (574) store-close boilerplate → `with_store` contextmanager.
- M7 `agent.py` `execute_tool` 130-line dispatcher + schema/impl split → registry in `agent_tools.py`.
- F6–F14 dup subscribe toggle, fetch-boilerplate hook, tap-target sizes, Google-signin busy guard, Settings number input, null-url StoryRow link, Favorites `Row`-as-fn, dead CSS prune.

## Fix phases

Logging (0026) lands **first** so every fix below emits real logs.

- **P1 — Security (S1, S2, S3).** Gate owner-bootstrap on `email_verified`; reject exchange when the claim is explicitly false. Default `cookie_secure()` to true (dev opt-out). IP-key the exchange/session limiter.
- **P2 — Concurrency/correctness (C1–C5).** Lock the RateLimiter. Guard chat tool dispatch + emit a clean error event + persist a fallback assistant message. Re-check budget at the top of each chat loop iteration. Dedup `get_or_build_brief` and `maybe_kick` via `INSERT OR IGNORE` / conditional-UPDATE claims.
- **P3 — Shared helpers (M2, M3, M4, H2).** `ratelimit.rate_limit_error()`; `_story_dict()`; an `llm_errors()` context manager; `provision_runner.start_run()` owning generator wiring + brief gate (both surfaces call it).
- **P4 — File splits (M1, M5, M7).** Extract `dashboard_topics.py` + `dashboard_briefs.py` (dashboard_api under cap); move `api.ts` interfaces to `api.types.ts`; move agent tool bodies to a registry in `agent_tools.py`.
- **P5 — Frontend/mobile (F1–F5, plus cheap lows).** Mobile tour anchors; cancellation guards; Headlines topic-guard; `.detail-actions` wrap; collapsible mobile chat sidebar; Google busy guard; null-url StoryRow; dead-CSS prune.

Each phase ends with `pytest` + `npm run build` green before moving on. Lower-value
lows (M6, fetch-hook, tap targets) are noted in `roadmap.md` if not reached.
</content>
