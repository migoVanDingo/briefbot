"""bbv2 command-line interface.

Commands:
  init
  topic add <slug> --name --description   |   topic list
  source add --topic <slug> --type rss|site --url --name [--weight] [--status]
  source list [--topic <slug>]
  collect [--topic <slug>]
  items --topic <slug> [--since 24h] [--limit N]
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone

from . import config
from .collect import collect
from .store import Store

_UNIT_SECONDS = {"m": 60, "h": 3600, "d": 86400}


def parse_since(value: str | None) -> str | None:
    """Parse a relative window like '24h' / '7d' / '30m' into an ISO cutoff."""
    if not value:
        return None
    v = value.strip().lower()
    if len(v) >= 2 and v[-1] in _UNIT_SECONDS and v[:-1].isdigit():
        seconds = int(v[:-1]) * _UNIT_SECONDS[v[-1]]
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=seconds)
        return cutoff.replace(microsecond=0).isoformat()
    return None


def _store() -> Store:
    return Store(config.db_path())


def cmd_init(_: argparse.Namespace) -> None:
    store = _store()
    print(f"Initialized bbv2 database at {config.db_path()}")
    store.close()


def cmd_topic_add(args: argparse.Namespace) -> None:
    store = _store()
    tid = store.add_topic(args.slug, args.name or args.slug, args.description or "")
    print(f"topic '{args.slug}' (id={tid})")
    store.close()


def cmd_topic_list(_: argparse.Namespace) -> None:
    store = _store()
    for t in store.list_topics():
        print(f"{t['slug']:20} {t['name']}")
    store.close()


def cmd_source_add(args: argparse.Namespace) -> None:
    store = _store()
    topic = store.get_topic(args.topic)
    if not topic:
        raise SystemExit(f"unknown topic '{args.topic}' — add it first")
    sid = store.add_source(
        type=args.type,
        url=args.url,
        name=args.name,
        weight=args.weight,
        status=args.status,
    )
    store.link_topic_source(int(topic["id"]), sid)
    print(f"source '{args.name}' (id={sid}) → topic '{args.topic}'")
    store.close()


def cmd_source_list(args: argparse.Namespace) -> None:
    store = _store()
    for s in store.list_sources(args.topic):
        print(f"[{s['type']:4}] {s['name']:30} {s['status']:9} {s['url']}")
    store.close()


def cmd_discover(args: argparse.Namespace) -> None:
    from .brave import DiscoveryError
    from .discovery import discover_sources

    store = _store()
    try:
        stats = discover_sources(
            store, args.topic, per_query=args.per_query, max_candidates=args.max
        )
    except DiscoveryError as exc:
        raise SystemExit(str(exc))
    print(json.dumps(stats, indent=2))
    print("\nReview with: bbv2 source candidates --topic " + args.topic)
    store.close()


def cmd_source_candidates(args: argparse.Namespace) -> None:
    store = _store()
    for s in store.list_candidates(args.topic):
        print(f"id={s['id']:<4} {s['name'][:40]:40} {s['url']}")
    store.close()


def cmd_source_approve(args: argparse.Namespace) -> None:
    store = _store()
    store.set_source_status(args.id, "active")
    print(f"approved source id={args.id} → active")
    store.close()


def cmd_source_reject(args: argparse.Namespace) -> None:
    store = _store()
    store.set_source_status(args.id, "rejected")
    print(f"rejected source id={args.id}")
    store.close()


def cmd_collect(args: argparse.Namespace) -> None:
    store = _store()
    stats = collect(store, topic_slug=args.topic)
    print(json.dumps(stats, indent=2))
    store.close()


def cmd_token_create(args: argparse.Namespace) -> None:
    store = _store()
    slugs = [s.strip() for s in (args.topics or "").split(",") if s.strip()]
    if not slugs:
        raise SystemExit("provide --topics as a comma-separated list of slugs")
    known = {t["slug"] for t in store.list_topics()}
    for slug in slugs:
        if slug not in known:
            print(f"warning: topic '{slug}' doesn't exist yet (token still scoped to it)")
    token = store.create_token(args.label, slugs)
    print(f"token for '{args.label}' (scope: {', '.join(slugs)}):\n{token}")
    print("Store it now — it isn't shown again.")
    store.close()


def cmd_token_list(_: argparse.Namespace) -> None:
    store = _store()
    for t in store.list_tokens():
        masked = t["token"][:6] + "…"
        state = " [REVOKED]" if t.get("revoked_at") else ""
        print(
            f"{t['label']:16} {masked:8} [{', '.join(t['topics'])}]  {t['created_at']}{state}"
        )
    store.close()


def cmd_token_revoke(args: argparse.Namespace) -> None:
    store = _store()
    n = store.revoke_token(args.token_or_label)
    if n:
        print(f"revoked {n} token(s) matching '{args.token_or_label}'")
    else:
        print(f"no active token matched '{args.token_or_label}'")
    store.close()


def cmd_serve(args: argparse.Namespace) -> None:
    import logging

    import uvicorn
    from fastapi.middleware.cors import CORSMiddleware

    from .api import create_app
    from .auth import verify_token
    from .dashboard_api import add_dashboard_routes

    log = logging.getLogger("bbv2.serve")

    if config.jwt_secret_is_default():
        log.warning(
            "BBV2_JWT_SECRET is unset — using an ephemeral per-process secret. "
            "Sessions won't survive a restart. Set it in production (devops.md)."
        )
    # Auth cookies over plain HTTP are a session-theft risk in production. Local
    # http dev legitimately needs Secure=off, so warn rather than refuse.
    if not config.cookie_secure() and args.host not in ("127.0.0.1", "localhost"):
        log.warning(
            "BBV2_COOKIE_SECURE is off but binding %s (not localhost) — set "
            "BBV2_COOKIE_SECURE=true so auth cookies are HTTPS-only.", args.host
        )

    # check_same_thread=False: API serves on a threadpool over one connection (WAL).
    store = Store(config.db_path(), check_same_thread=False)
    # Any provision run still 'running' here lost its worker on the last restart —
    # mark it interrupted so the UI shows no zombie pipelines (0023).
    orphaned = store.fail_orphaned_runs() + store.fail_orphaned_discovery_runs()
    if orphaned:
        log.info("marked %d interrupted background run(s) from a prior restart", orphaned)
    # Background image gens that were mid-flight at the last restart are stuck
    # 'pending' forever otherwise (the atomic claim only fires from non-pending).
    stuck = store.reset_orphaned_image_jobs()
    if stuck:
        log.info("reset %d stuck 'pending' image job(s) from a prior restart", stuck)
    app = create_app(store)  # consumer API (service tokens)
    # add_dashboard_routes also wires /api/auth/* (Firebase exchange → bbv2 session).
    add_dashboard_routes(app, store, verify_token)  # /api/* (Firebase)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.allowed_origins(),  # ALLOWED_ORIGINS env (Tailscale deploy)
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from fastapi import Request
    from fastapi.responses import JSONResponse

    @app.exception_handler(Exception)
    async def _on_unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Expected 4xx (HTTPException/validation) have their own handlers; this only
        # fires for genuinely unhandled errors — log the traceback so 500s aren't silent.
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "internal server error"})

    @app.on_event("shutdown")
    def _close_store() -> None:
        store.close_all()

    log.info("serving bbv2 on %s:%s (log level %s)", args.host, args.port, config.log_level())
    # Align uvicorn's own access/error logs to our level; keep its default handlers
    # so request logs show up alongside ours in journald/stderr.
    uvicorn.run(app, host=args.host, port=args.port, log_level=config.log_level().lower())


def cmd_items(args: argparse.Namespace) -> None:
    store = _store()
    rows = store.items_for_topic(
        args.topic, since_iso=parse_since(args.since), limit=args.limit
    )
    for r in rows:
        when = r["published_at"] or r["fetched_at"]
        print(f"{when}  [{r['source_name']}]  {r['title']}")
        if r["url"]:
            print(f"    {r['url']}")
    print(f"\n{len(rows)} item(s)")
    store.close()


def _str2bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _require_user(store: Store, email: str):
    user = store.get_user(email)
    if not user:
        raise SystemExit(f"unknown user '{email}' — add it first")
    return user


def _require_topic(store: Store, slug: str):
    topic = store.get_topic(slug)
    if not topic:
        raise SystemExit(f"unknown topic '{slug}'")
    return topic


def cmd_user_add(args: argparse.Namespace) -> None:
    store = _store()
    uid = store.add_user(args.name, args.email, role=args.role)
    print(f"user '{args.name}' <{args.email}> (id={uid})")
    store.close()


def cmd_user_list(_: argparse.Namespace) -> None:
    store = _store()
    for u in store.list_users():
        status = (u["status"] if "status" in u.keys() else "active") or "active"
        last = (u["last_login_at"] if "last_login_at" in u.keys() else None) or "-"
        print(
            f"id={u['id']:<3} {u['name']:16} {u['email']:28} "
            f"{u['role']:7} {status:8} last_login={last}"
        )
    store.close()


def cmd_user_set_role(args: argparse.Namespace) -> None:
    store = _store()
    user = _require_user(store, args.email)
    if user["role"] == "owner":
        raise SystemExit("refusing to change the owner role (bootstrap via ADMIN_EMAILS)")
    if args.role not in ("admin", "user", "service"):
        raise SystemExit("role must be one of: admin, user, service")
    store.set_user_role(args.email, args.role)
    print(f"{args.email} role → {args.role}")
    store.close()


def cmd_user_disable(args: argparse.Namespace) -> None:
    store = _store()
    user = _require_user(store, args.email)
    if user["role"] == "owner":
        raise SystemExit("refusing to disable the owner")
    store.set_user_status(args.email, "disabled")
    n = store.revoke_user_sessions(int(user["id"]))
    store.log_auth_event(int(user["id"]), "disabled")
    print(f"{args.email} disabled; revoked {n} active session(s)")
    store.close()


def cmd_user_enable(args: argparse.Namespace) -> None:
    store = _store()
    _require_user(store, args.email)
    store.set_user_status(args.email, "active")
    print(f"{args.email} enabled")
    store.close()


def cmd_session_revoke(args: argparse.Namespace) -> None:
    store = _store()
    user = _require_user(store, args.user)
    n = store.revoke_user_sessions(int(user["id"]))
    store.log_auth_event(int(user["id"]), "revoked")
    print(f"revoked {n} active session(s) for {args.user}")
    store.close()


def cmd_subscribe(args: argparse.Namespace) -> None:
    store = _store()
    user = _require_user(store, args.user)
    topic = _require_topic(store, args.topic)
    store.subscribe(int(user["id"]), int(topic["id"]))
    print(f"{args.user} subscribed to '{args.topic}'")
    store.close()


def cmd_unsubscribe(args: argparse.Namespace) -> None:
    store = _store()
    user = _require_user(store, args.user)
    topic = _require_topic(store, args.topic)
    store.unsubscribe(int(user["id"]), int(topic["id"]))
    print(f"{args.user} unsubscribed from '{args.topic}'")
    store.close()


def cmd_settings_show(args: argparse.Namespace) -> None:
    store = _store()
    user = _require_user(store, args.user)
    s = store.get_user_settings(int(user["id"]))
    subs = [t["slug"] for t in store.user_subscriptions(int(user["id"]))]
    print(f"{user['email']}")
    print(f"  email_enabled : {bool(s['email_enabled'])}")
    print(f"  digest_limit  : {s['digest_limit']}")
    print(f"  last_digest_at: {s['last_digest_at']}")
    print(f"  subscriptions : {', '.join(subs) or '(none)'}")
    store.close()


def cmd_settings_set(args: argparse.Namespace) -> None:
    store = _store()
    user = _require_user(store, args.user)
    store.set_user_settings(
        int(user["id"]),
        email_enabled=args.email_enabled,
        digest_limit=args.digest_limit,
    )
    print(f"updated settings for {user['email']}")
    store.close()


def cmd_brief(args: argparse.Namespace) -> None:
    from .brief import build_all_briefs, build_brief

    store = _store()
    if args.topic:
        b = build_brief(store, args.topic, date=args.date)
        if b is None:
            print(f"(no recent items for '{args.topic}')")
        else:
            print(
                json.dumps(
                    {
                        "topic": args.topic,
                        "title": b["title"],
                        "trending": len(b["trending"]),
                        "sources": len(b["sources"]),
                    },
                    indent=2,
                )
            )
    else:
        print(json.dumps(build_all_briefs(store, date=args.date), indent=2))
    store.close()


def cmd_quickscan(args: argparse.Namespace) -> None:
    from .review import quickscan_topic

    store = _store()
    slugs = [args.topic] if args.topic else [t["slug"] for t in store.list_topics()]
    for slug in slugs:
        print(f"{slug}: {json.dumps(quickscan_topic(store, slug))}")
    store.close()


def cmd_digest(args: argparse.Namespace) -> None:
    from .digest import run_digests
    from .notify import default_notifier

    store = _store()
    stats = run_digests(store, default_notifier(dry_run=args.dry_run))
    print(json.dumps(stats, indent=2))
    store.close()


def cmd_tick(_: argparse.Namespace) -> None:
    """Decoupled pull engine: due-based source discovery + story collection +
    relevance quickscan. Run hourly by cron."""
    from .scheduler import tick

    store = _store()
    print(json.dumps(tick(store), indent=2))
    store.close()


def cmd_nightly(args: argparse.Namespace) -> None:
    """Build subscribed topics' briefs and email subscribers. Run nightly (11pm)."""
    from .notify import default_notifier
    from .nightly import run_nightly

    store = _store()
    stats = run_nightly(store, default_notifier(dry_run=args.dry_run))
    print(json.dumps(stats, indent=2))
    store.close()


def cmd_embed_topics(_: argparse.Namespace) -> None:
    """Backfill the topic embedding index (0030): a meta vector for every topic +
    a vector for each recent brief. Idempotent — only embeds what's missing."""
    if not config.embeddings_enabled():
        raise SystemExit("OPENAI_API_KEY not set — embeddings disabled.")
    from .topic_index import embed_pending_briefs, ensure_meta_embeddings

    store = _store()
    meta = ensure_meta_embeddings(store)
    briefs = embed_pending_briefs(store)
    print(json.dumps({"meta_embedded": meta, "briefs_embedded": briefs}, indent=2))
    store.close()



def main(argv: list[str] | None = None) -> None:
    from .cli_parser import build_parser
    from .logging_setup import configure_logging

    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(verbose=getattr(args, "verbose", False))
    args.func(args)


if __name__ == "__main__":
    main()
