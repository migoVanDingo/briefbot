# 0023 — Durable provisioning pipelines (persist + observe anywhere)

**Status:** ✅ Implemented (2026-06-23) — all 6 phases; 164 backend pytest pass,
dashboard tsc/build clean.
**Phase:** Build · **Depends on:** 0009 (provision SSE), 0008 (chat agent).

## Implementation notes / deviations

- **`provision_runs` table + `store_provision.py` + `provision_runner.py`** (bounded
  `ThreadPoolExecutor`) as designed. `run_provision` binds `provision_topic` at
  import, so **tests monkeypatch `provision_runner.submit`** (sync) and/or
  `provision_runner.provision_topic` — noted in the chat tests.
- **`POST /…/provision` now returns `{run_id}`** (was SSE); **`GET /api/provisioning`**
  is the poll source; a shared **`useProvisioning` hook** drives both surfaces.
- **Chat keeps the inline look** — pills render from polled runs matched by the
  **pre-minted assistant `message_id`** (announced via a new `message` SSE event;
  `create_topic` now emits a single `topic_run` seed instead of per-stage events;
  `append_message` gained a `message_id` param). `ChatMessage.topics` is now
  effectively dead (kept in the type; pills come from `runs`).
- **Deviation — tool result/chip text:** because provisioning no longer blocks the
  turn, `create_topic` returns "setting up '<topic>'…" (status `provisioning`)
  instead of the old "created — N sources, M stories". The pills still show
  completion; `headline_ready` is set optimistically from the brief-window check.
  The agent narrates "setting them up now," which matches the desired UX.
- **Deviation — Topics page shows ALL active runs** (any surface, incl. chat-started),
  not just topics-initiated ones — so a chat-started setup is visible there too
  (matches "observe from anywhere"). Topics-initiated runs auto-subscribe on `done`.
- **Live advancement is poll-driven (~1.2s)**, replacing SSE stage streaming (as
  planned) — same visuals.
- Orphaned `running` rows → `error 'interrupted'` on `bbv2 serve` startup.
- `dashboard_api.py` sits at exactly the 600-line cap after the two new routes.

Make a topic's **provisioning pipeline** (discover → approve → collect → review →
[brief] → ready) **durable and observable from any surface**. Today it's
ephemeral: `provision_topic` is a sync generator whose stages stream into **one**
SSE connection (chat re-emits them as `topic_stage`; the Topics page renders them
live). There's **no server record**, so navigating away loses the visual — and
because the work runs *inside the request generator*, leaving can even abandon it
mid-flight. Goal: start a pipeline, browse away/refresh, come back, and see it
exactly where it is — in chat (same inline look) **and** on the Topics page — and
let the agent speak to it.

## Decisions (confirmed 2026-06-22)

1. **DB-persisted runs** — a `provision_runs` table (survives restart; keeps a
   history of past setups).
2. **Background execution + polling.** Provisioning runs in a **background thread**
   (so it finishes regardless of the client) and writes stage progress to the run
   row; clients **poll** `/api/provisioning` (~1.2s) to advance the UI. This
   *replaces* the live SSE stage-streaming — **identical visuals** (same
   `ProvisionPipeline` pills), the data source just moves from "streamed" to
   "polled," which is what makes it re-hydratable.
3. **Chat keeps its current look** — pills stay **inline in the agent's message**,
   re-hydrated from runs linked to that message (we mint the assistant message id
   up front so the link exists).
4. **Topics page** shows one pipeline **card per active run** above the topic list.
5. **Agent gets light awareness** — active runs are injected into its context so it
   can answer "how's my setup going?" (no new tool).

## Phase 1 — Run state + background execution

1.1 **`provision_runs` table** (schema + `_migrate`): `id` (`PRV…`), `user_id`,
    `conversation_id` (nullable), `message_id` (nullable), `surface`
    (`chat`|`topics`), `topic_slug`, `topic_name`, `stage` (current),
    `status` (`running`|`done`|`error`), `error`, `created_at`, `updated_at`.
    Index on `(user_id, status)` and `(conversation_id)`.
1.2 **`store_provision.py`** mixin: `create_run(...)`, `set_run_stage(id, stage)`,
    `finish_run(id, status, error=None)`, `active_runs(user_id)`,
    `runs_for_conversation(cid)`, `recent_runs(user_id, window_s)`,
    `fail_orphaned_runs()` (startup: any `running` row → `error 'interrupted'`,
    since its thread died on restart).
1.3 **`provision.run_provision(store, run_id, slug, *, review_generate,
    brief_generate)`** — wraps the existing `provision_topic` generator, mapping
    each `stage` event → `set_run_stage`, final → `finish_run`. Best-effort; all
    exceptions → `finish_run(error)`. Runs on a small **bounded thread pool**
    (cap concurrency, e.g. 3, so we don't hammer Brave/feeds). Each thread uses
    the Store's per-thread SQLite connection (already supported).

## Phase 2 — API

2.1 **`POST /api/topics/{slug}/provision`** (surface `topics`) → create a run,
    submit it to the pool, return **`{run_id}`** immediately (no more SSE here).
    Rate-limited + budget-checked as today.
2.2 **`GET /api/provisioning`** (auth) → the caller's `running` + recently-`done`
    runs (last ~5 min) with full stage/status; optional `?conversation=<cid>`.
    The poll source for every surface.
2.3 **Chat `create_topic`** (`agent._create_topic_events`): create a run linked to
    `conversation_id` + the turn's `message_id`, submit to the pool, and emit a
    single lightweight **`topic_run` {slug, name, run_id, stage:"discovering"}**
    SSE event so the pill appears instantly in the live message. Drop the
    per-stage streaming; advancement comes from the poll.

## Phase 3 — Chat: same look, now durable

3.1 **Mint the assistant `message_id` up front** in `run_chat_turn`; thread it into
    `_create_topic_events` (→ `run.message_id`) and `append_message(..., message_id=)`
    (add the optional param to `store_chat.append_message`).
3.2 **`Chat.tsx`**: on conversation load, call `GET /api/provisioning?conversation`
    and **attach runs to messages by `message_id`** → render `ProvisionPipeline`
    (unchanged). **Poll** every ~1.2s while any attached run is `running`; stop when
    all settle. The live turn uses the same poll loop (seeded by the `topic_run`
    event), so first-run and returning-user paths are identical.
3.3 `ChatMessage.topics` becomes server-sourced (mapped from runs) rather than only
    accumulated from streamed events.

## Phase 4 — Topics page cards

4.1 **`TopicsHome`**: fetch `GET /api/provisioning`; render a `ProvisionPipeline`
    card per active run **above the topic list**; poll while running; on a run's
    completion, refresh the topic list (so the new topic appears with **Subscribe**).
    (The user-initiated create flow there now also just starts a run + polls.)

## Phase 5 — Agent awareness

5.1 Inject a short note into the agent's context each turn — "active setups: crypto
    (collecting), firearms (discovering)" from `active_runs` — so the model can
    answer status questions naturally. No tool, no new events.

## Phase 6 — Verify + docs

- **Tests** (offline; run the pool **synchronously** via an injectable executor so
  no real threads in tests): run lifecycle (create → stage updates → done/error);
  `active_runs` / `runs_for_conversation`; `POST /provision` returns `run_id` +
  records a run; `GET /api/provisioning` shape + per-conversation filter;
  `fail_orphaned_runs` on startup; `append_message` honors a supplied id. Frontend
  `tsc`/build.
- Docs: `architecture.md` (provisioning is now a tracked background job + poll),
  `roadmap.md`. Update `0009`'s SSE note.

## Risks / notes

- **Live turn no longer blocks on provisioning** — the agent's text returns right
  away and pills fill in via poll (~1.2s cadence). Same visuals, slightly different
  timing. This is the one behavior change.
- **Restart mid-run** kills the thread; `fail_orphaned_runs()` marks those rows
  `error 'interrupted'` on next boot (no zombie "running" cards). A "retry" button
  is a possible follow-up.
- **Concurrency cap** on the pool protects Brave/feeds; excess runs queue.
- **Polling cost** is tiny (a few rows) and only while runs are active.

## Done when

A user starts setting up topics in chat, clicks **View your headlines**, comes
back to `/chat`, and the pipeline is **still there, advancing**, in the same inline
message — and the same run shows as a **card on the Topics page**, and asking the
agent "how's it going?" gets an accurate answer. Closing the tab and reopening
re-hydrates it too; a backend restart leaves no zombie pipelines.
