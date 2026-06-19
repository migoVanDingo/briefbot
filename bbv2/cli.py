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


def cmd_collect(args: argparse.Namespace) -> None:
    store = _store()
    stats = collect(store, topic_slug=args.topic)
    print(json.dumps(stats, indent=2))
    store.close()


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

    p_collect = sub.add_parser("collect")
    p_collect.add_argument("--topic")
    p_collect.set_defaults(func=cmd_collect)

    p_items = sub.add_parser("items")
    p_items.add_argument("--topic", required=True)
    p_items.add_argument("--since")
    p_items.add_argument("--limit", type=int, default=20)
    p_items.set_defaults(func=cmd_items)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
