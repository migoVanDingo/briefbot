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
        print(f"{t['label']:16} {masked:8} [{', '.join(t['topics'])}]  {t['created_at']}")
    store.close()


def cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn
    from fastapi.middleware.cors import CORSMiddleware

    from .api import create_app
    from .auth import verify_token
    from .dashboard_api import add_dashboard_routes

    # check_same_thread=False: API serves on a threadpool over one connection (WAL).
    store = Store(config.db_path(), check_same_thread=False)
    app = create_app(store)  # consumer API (service tokens)
    add_dashboard_routes(app, store, verify_token)  # /api/* (Firebase)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    uvicorn.run(app, host=args.host, port=args.port)


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
        print(f"id={u['id']:<3} {u['name']:16} {u['email']:28} {u['role']}")
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bbv2")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init").set_defaults(func=cmd_init)

    p_topic = sub.add_parser("topic")
    topic_sub = p_topic.add_subparsers(dest="topic_cmd", required=True)
    p_ta = topic_sub.add_parser("add")
    p_ta.add_argument("slug")
    p_ta.add_argument("--name")
    p_ta.add_argument("--description")
    p_ta.set_defaults(func=cmd_topic_add)
    topic_sub.add_parser("list").set_defaults(func=cmd_topic_list)

    p_source = sub.add_parser("source")
    source_sub = p_source.add_subparsers(dest="source_cmd", required=True)
    p_sa = source_sub.add_parser("add")
    p_sa.add_argument("--topic", required=True)
    p_sa.add_argument("--type", required=True, choices=["rss", "site"])
    p_sa.add_argument("--url", required=True)
    p_sa.add_argument("--name", required=True)
    p_sa.add_argument("--weight", type=float, default=1.0)
    p_sa.add_argument("--status", default="active", choices=["active", "candidate", "rejected"])
    p_sa.set_defaults(func=cmd_source_add)
    p_sl = source_sub.add_parser("list")
    p_sl.add_argument("--topic")
    p_sl.set_defaults(func=cmd_source_list)
    p_sc = source_sub.add_parser("candidates")
    p_sc.add_argument("--topic")
    p_sc.set_defaults(func=cmd_source_candidates)
    p_sap = source_sub.add_parser("approve")
    p_sap.add_argument("id", type=int)
    p_sap.set_defaults(func=cmd_source_approve)
    p_srj = source_sub.add_parser("reject")
    p_srj.add_argument("id", type=int)
    p_srj.set_defaults(func=cmd_source_reject)

    p_discover = sub.add_parser("discover")
    p_discover.add_argument("--topic", required=True)
    p_discover.add_argument("--per-query", type=int, default=8, dest="per_query")
    p_discover.add_argument("--max", type=int, default=20)
    p_discover.set_defaults(func=cmd_discover)

    p_collect = sub.add_parser("collect")
    p_collect.add_argument("--topic")
    p_collect.set_defaults(func=cmd_collect)

    p_items = sub.add_parser("items")
    p_items.add_argument("--topic", required=True)
    p_items.add_argument("--since")
    p_items.add_argument("--limit", type=int, default=20)
    p_items.set_defaults(func=cmd_items)

    p_token = sub.add_parser("token")
    token_sub = p_token.add_subparsers(dest="token_cmd", required=True)
    p_tc = token_sub.add_parser("create")
    p_tc.add_argument("--label", required=True)
    p_tc.add_argument("--topics", required=True, help="comma-separated topic slugs")
    p_tc.set_defaults(func=cmd_token_create)
    token_sub.add_parser("list").set_defaults(func=cmd_token_list)

    p_serve = sub.add_parser("serve")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8080)
    p_serve.set_defaults(func=cmd_serve)

    p_user = sub.add_parser("user")
    user_sub = p_user.add_subparsers(dest="user_cmd", required=True)
    p_ua = user_sub.add_parser("add")
    p_ua.add_argument("--name", required=True)
    p_ua.add_argument("--email", required=True)
    p_ua.add_argument("--role", default="human", choices=["human", "service"])
    p_ua.set_defaults(func=cmd_user_add)
    user_sub.add_parser("list").set_defaults(func=cmd_user_list)

    p_sub = sub.add_parser("subscribe")
    p_sub.add_argument("--user", required=True)
    p_sub.add_argument("--topic", required=True)
    p_sub.set_defaults(func=cmd_subscribe)
    p_unsub = sub.add_parser("unsubscribe")
    p_unsub.add_argument("--user", required=True)
    p_unsub.add_argument("--topic", required=True)
    p_unsub.set_defaults(func=cmd_unsubscribe)

    p_settings = sub.add_parser("settings")
    settings_sub = p_settings.add_subparsers(dest="settings_cmd", required=True)
    p_ss = settings_sub.add_parser("show")
    p_ss.add_argument("--user", required=True)
    p_ss.set_defaults(func=cmd_settings_show)
    p_sset = settings_sub.add_parser("set")
    p_sset.add_argument("--user", required=True)
    p_sset.add_argument("--email-enabled", type=_str2bool, dest="email_enabled")
    p_sset.add_argument("--digest-limit", type=int, dest="digest_limit")
    p_sset.set_defaults(func=cmd_settings_set)

    p_digest = sub.add_parser("digest")
    p_digest.add_argument("--dry-run", action="store_true", dest="dry_run")
    p_digest.set_defaults(func=cmd_digest)

    p_brief = sub.add_parser("brief")
    p_brief.add_argument("--topic", help="slug; omit to build briefs for all topics")
    p_brief.add_argument("--date", help="YYYY-MM-DD (default: today, UTC)")
    p_brief.set_defaults(func=cmd_brief)

    p_quickscan = sub.add_parser("quickscan")
    p_quickscan.add_argument("--topic", help="slug; omit to scan all topics")
    p_quickscan.set_defaults(func=cmd_quickscan)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
