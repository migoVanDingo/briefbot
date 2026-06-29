"""CLI argument parser (split from cli.py to keep it under the size cap).

`build_parser` wires every subcommand to its `cmd_*` handler in `cli`. The `cli`
import is lazy (inside the function) so there's no import cycle — `cli.main`
imports this module.
"""

from __future__ import annotations

import argparse

from . import config

def build_parser() -> argparse.ArgumentParser:
    from . import cli  # lazy: avoid an import cycle
    parser = argparse.ArgumentParser(prog="bbv2")
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="verbose (DEBUG) logging; overrides BBV2_LOG_LEVEL",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init").set_defaults(func=cli.cmd_init)

    p_topic = sub.add_parser("topic")
    topic_sub = p_topic.add_subparsers(dest="topic_cmd", required=True)
    p_ta = topic_sub.add_parser("add")
    p_ta.add_argument("slug")
    p_ta.add_argument("--name")
    p_ta.add_argument("--description")
    p_ta.set_defaults(func=cli.cmd_topic_add)
    topic_sub.add_parser("list").set_defaults(func=cli.cmd_topic_list)

    p_source = sub.add_parser("source")
    source_sub = p_source.add_subparsers(dest="source_cmd", required=True)
    p_sa = source_sub.add_parser("add")
    p_sa.add_argument("--topic", required=True)
    p_sa.add_argument("--type", required=True, choices=["rss", "site"])
    p_sa.add_argument("--url", required=True)
    p_sa.add_argument("--name", required=True)
    p_sa.add_argument("--weight", type=float, default=1.0)
    p_sa.add_argument("--status", default="active", choices=["active", "candidate", "rejected"])
    p_sa.set_defaults(func=cli.cmd_source_add)
    p_sl = source_sub.add_parser("list")
    p_sl.add_argument("--topic")
    p_sl.set_defaults(func=cli.cmd_source_list)
    p_sc = source_sub.add_parser("candidates")
    p_sc.add_argument("--topic")
    p_sc.set_defaults(func=cli.cmd_source_candidates)
    p_sap = source_sub.add_parser("approve")
    p_sap.add_argument("id", type=int)
    p_sap.set_defaults(func=cli.cmd_source_approve)
    p_srj = source_sub.add_parser("reject")
    p_srj.add_argument("id", type=int)
    p_srj.set_defaults(func=cli.cmd_source_reject)

    p_discover = sub.add_parser("discover")
    p_discover.add_argument("--topic", required=True)
    p_discover.add_argument("--per-query", type=int, default=8, dest="per_query")
    p_discover.add_argument("--max", type=int, default=20)
    p_discover.set_defaults(func=cli.cmd_discover)

    p_collect = sub.add_parser("collect")
    p_collect.add_argument("--topic")
    p_collect.set_defaults(func=cli.cmd_collect)

    p_items = sub.add_parser("items")
    p_items.add_argument("--topic", required=True)
    p_items.add_argument("--since")
    p_items.add_argument("--limit", type=int, default=20)
    p_items.set_defaults(func=cli.cmd_items)

    p_token = sub.add_parser("token")
    token_sub = p_token.add_subparsers(dest="token_cmd", required=True)
    p_tc = token_sub.add_parser("create")
    p_tc.add_argument("--label", required=True)
    p_tc.add_argument("--topics", required=True, help="comma-separated topic slugs")
    p_tc.set_defaults(func=cli.cmd_token_create)
    token_sub.add_parser("list").set_defaults(func=cli.cmd_token_list)
    p_trv = token_sub.add_parser("revoke")
    p_trv.add_argument("token_or_label", help="full token or label to revoke")
    p_trv.set_defaults(func=cli.cmd_token_revoke)

    p_serve = sub.add_parser("serve")
    p_serve.add_argument("--host", default=config.serve_host())
    p_serve.add_argument("--port", type=int, default=8080)
    p_serve.set_defaults(func=cli.cmd_serve)

    p_user = sub.add_parser("user")
    user_sub = p_user.add_subparsers(dest="user_cmd", required=True)
    p_ua = user_sub.add_parser("add")
    p_ua.add_argument("--name", required=True)
    p_ua.add_argument("--email", required=True)
    p_ua.add_argument("--role", default="human", choices=["human", "service"])
    p_ua.set_defaults(func=cli.cmd_user_add)
    user_sub.add_parser("list").set_defaults(func=cli.cmd_user_list)
    p_usr = user_sub.add_parser("set-role")
    p_usr.add_argument("email")
    p_usr.add_argument("role", choices=["admin", "user", "service"])
    p_usr.set_defaults(func=cli.cmd_user_set_role)
    p_udis = user_sub.add_parser("disable")
    p_udis.add_argument("email")
    p_udis.set_defaults(func=cli.cmd_user_disable)
    p_uen = user_sub.add_parser("enable")
    p_uen.add_argument("email")
    p_uen.set_defaults(func=cli.cmd_user_enable)

    p_session = sub.add_parser("session")
    session_sub = p_session.add_subparsers(dest="session_cmd", required=True)
    p_srev = session_sub.add_parser("revoke")
    p_srev.add_argument("--user", required=True)
    p_srev.set_defaults(func=cli.cmd_session_revoke)

    p_sub = sub.add_parser("subscribe")
    p_sub.add_argument("--user", required=True)
    p_sub.add_argument("--topic", required=True)
    p_sub.set_defaults(func=cli.cmd_subscribe)
    p_unsub = sub.add_parser("unsubscribe")
    p_unsub.add_argument("--user", required=True)
    p_unsub.add_argument("--topic", required=True)
    p_unsub.set_defaults(func=cli.cmd_unsubscribe)

    p_settings = sub.add_parser("settings")
    settings_sub = p_settings.add_subparsers(dest="settings_cmd", required=True)
    p_ss = settings_sub.add_parser("show")
    p_ss.add_argument("--user", required=True)
    p_ss.set_defaults(func=cli.cmd_settings_show)
    p_sset = settings_sub.add_parser("set")
    p_sset.add_argument("--user", required=True)
    p_sset.add_argument("--email-enabled", type=cli._str2bool, dest="email_enabled")
    p_sset.add_argument("--digest-limit", type=int, dest="digest_limit")
    p_sset.set_defaults(func=cli.cmd_settings_set)

    p_digest = sub.add_parser("digest")
    p_digest.add_argument("--dry-run", action="store_true", dest="dry_run")
    p_digest.set_defaults(func=cli.cmd_digest)

    p_brief = sub.add_parser("brief")
    p_brief.add_argument("--topic", help="slug; omit to build briefs for all topics")
    p_brief.add_argument("--date", help="YYYY-MM-DD (default: today, UTC)")
    p_brief.set_defaults(func=cli.cmd_brief)

    p_quickscan = sub.add_parser("quickscan")
    p_quickscan.add_argument("--topic", help="slug; omit to scan all topics")
    p_quickscan.set_defaults(func=cli.cmd_quickscan)

    sub.add_parser("tick").set_defaults(func=cli.cmd_tick)

    p_nightly = sub.add_parser("nightly")
    p_nightly.add_argument("--dry-run", action="store_true", dest="dry_run")
    p_nightly.set_defaults(func=cli.cmd_nightly)

    sub.add_parser("embed-topics").set_defaults(func=cli.cmd_embed_topics)

    return parser

