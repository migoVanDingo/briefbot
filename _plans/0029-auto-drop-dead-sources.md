# 0029 — Auto-drop dead / blocked feeds

Sources that go dead or behind a paywall keep failing every collect cycle, spamming
the logs (`fetch failed: Feed HTTP 401/404 …`) and wasting fetches. Auto-disable a
source after a streak of **droppable** 4xx fetch failures.

## Policy (decided with the owner)

- **Droppable statuses:** `401` (auth/paywall), `403` (forbidden/blocked), `404`
  (not found), `410` (gone). **Never** `429` (rate-limit — backoff handles it),
  `5xx`, timeouts, or SSL/connection errors (all transient).
- **Threshold:** disable after **3 consecutive** droppable failures; any successful
  fetch resets the streak. **`410` Gone disables immediately** (definitive).
  Configurable via `BBV2_SOURCE_DROP_THRESHOLD` (0 = off).
- **Action:** **disable** (status `disabled`) + record `last_error` (e.g. "HTTP 404")
  — reversible, keeps collected items, shown in the admin source list. Not a delete.

## Implementation

- **Schema:** `sources` gains `consecutive_failures` (default 0), `last_error`,
  `last_error_at` (via `_migrate` + `schema.py`).
- **Store:** `bump_source_failure(id, error) → count`, `clear_source_failures(id)`,
  `disable_source(id, reason)`.
- **Collect:** `collect_source` tracks per-source `any_success` + the last droppable
  failure across its feed URLs, then `_update_source_health` applies the policy
  (reset on success / immediate 410 / streak-to-threshold). `DROPPABLE_STATUSES`
  + `config.source_drop_threshold()`.
- **Admin:** the source list returns `last_error`; TopicDetail shows
  "disabled · HTTP 404" on the chip. Re-enabling a source (`/sources/{id}/enable`)
  **clears the streak** so one more failure doesn't instantly re-disable it.

Existing dead feeds (AP, CBS, …) auto-disable within a few cron cycles. Tests in
`tests/test_source_health.py` (streak→disable, success-reset, 410-immediate,
429/5xx ignored, threshold=0 off, enable-resets).
</content>
