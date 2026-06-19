# 0005 — Multi-user + Settings + Email

**Status:** ✅ Implemented (2026-06-19) — email validated via dry-run (Mailgun wired, not live-sent)
**Date:** 2026-06-19
**Phase:** Build · **Depends on:** 0002 ✅, 0003 ✅, 0004 ✅

> **Done.** 22 tests pass (visibility/settings/digest with a fake notifier).
> Verified live: collect → add user → subscribe → `settings` → `digest --dry-run`
> printed the per-user email of only-new items; a second run sent 0 (checkpoint
> advanced); `email_enabled=false` dropped the user. Real Mailgun is wired but
> only flips on once `MAILGUN_*` env is set.

## Goal

Add **users** (me + mom + brother), **topic subscriptions** with per-user
visibility, **user settings**, and **per-user email** — a recent-items **digest**
sent to each user's own address, gated by their settings. This is the "no
overlapping data unless you subscribe to shared topics" model from 0001, plus the
email half of briefbot brought forward (per recipient, not just me).

## Guardrails (unchanged)

og briefbot untouched; bbv2 reads/writes only its own DB.

## Scope

- **In:** users / subscriptions / user_settings schema + store; per-user item
  visibility (`items_for_user`); a notifier abstraction (Log + Mailgun backends);
  a settings-gated **digest** job with a `last_digest_at` checkpoint; CLI for
  users / subscribe / settings / digest.
- **Out:** the LLM daily brief (phase 6 — the digest here is a plain recent-items
  list, no LLM); the dashboard; unifying service-account tokens with user
  subscriptions (0003 `token_topics` stays as-is; see Notes).

## Data model

```sql
users(id, name, email UNIQUE, role, created_at)        -- role: human | service
subscriptions(user_id, topic_id, PRIMARY KEY(user_id, topic_id))
user_settings(user_id PRIMARY KEY, email_enabled, digest_limit, last_digest_at)
```

**Visibility:** a user sees an item iff it's in a topic they subscribe to
(`subscriptions → topics → item_topics → items`). No shared subscription → no
shared data.

## Notifier abstraction

`bbv2/notify.py`:
- `Notifier` protocol: `send(to: str, subject: str, body: str)`.
- `LogNotifier` — prints what it would send (used by `--dry-run` and as a safe
  default).
- `MailgunNotifier` — posts to the Mailgun API; constructed only when
  `MAILGUN_API_KEY` / `MAILGUN_DOMAIN` / `MAILGUN_FROM` are set.

## Digest job

```
for each user with email_enabled:
  since   = user_settings.last_digest_at
  items   = items_for_user(user, since, limit=digest_limit)   # newest first
  if no items: skip (don't email an empty digest)
  body    = render(items grouped by topic: title + url)
  notifier.send(user.email, "Your news digest (N new)", body)
  set last_digest_at = newest fetched_at seen   # next run only sends newer
```

Run on a cron later (alongside collect). The digest is **non-LLM**; the LLM daily
brief replaces/augments it in phase 6.

## CLI

```bash
bbv2 user add --name "Mom" --email mom@example.com
bbv2 user list
bbv2 subscribe   --user mom@example.com --topic crypto
bbv2 unsubscribe --user mom@example.com --topic crypto
bbv2 settings show --user mom@example.com
bbv2 settings set  --user mom@example.com --email-enabled true --digest-limit 15
bbv2 digest [--dry-run]        # dry-run uses LogNotifier (no real send)
```

## Module layout

```
bbv2/
  notify.py    Notifier protocol + LogNotifier + MailgunNotifier
  digest.py    render + run_digests(store, notifier)
  store.py     + users/subscriptions/user_settings methods, items_for_user
  cli.py       + user, subscribe/unsubscribe, settings, digest
  config.py    + mailgun_config()
```

## Tests (offline)

- users/subscriptions: add, subscribe, `items_for_user` only returns subscribed
  topics' items; unsubscribe hides them.
- settings: defaults on user create; `set`/`show` roundtrip.
- digest: a **fake notifier** captures sends — a user with `email_enabled` and
  new items gets one send; `last_digest_at` advances so a second run sends
  nothing; `email_enabled=false` → no send; empty items → no send.
- Mailgun is **not** called in tests.

## Tasks

- [x] **1** Schema + store: users, subscriptions, user_settings; `add_user`,
      `get_user`, `list_users`, `subscribe`, `unsubscribe`, `user_subscriptions`,
      `get_user_settings`, `set_user_settings`, `items_for_user`,
      `users_with_email_enabled`.
- [x] **2** `bbv2/notify.py`: protocol + LogNotifier + MailgunNotifier;
      `config.mailgun_config()`.
- [x] **3** `bbv2/digest.py`: render + `run_digests` with `last_digest_at`.
- [x] **4** CLI: user / subscribe / unsubscribe / settings / digest.
- [x] **5** Tests per above (fake notifier; no network).
- [x] **6** Docs: CLAUDE.md commands + layout.

## Done when

Add users, subscribe them to topics, `items_for_user` respects subscriptions,
`digest --dry-run` prints per-user digests of only-new items and checkpoints, and
`email_enabled=false` suppresses a user. Tests pass; og briefbot untouched.

## Notes

- **Service accounts vs users:** 0003 tokens scope via `token_topics` and stay as
  they are. A future cleanup can model a service account as a `role='service'`
  user whose token scope = its subscriptions — deferred, not needed now.
- **Real email** is wired (Mailgun) but only validated via `--dry-run`/tests here;
  flip it on once `MAILGUN_*` env is set.
