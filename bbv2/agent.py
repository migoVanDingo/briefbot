"""Agentic chat for bbv2 (Haiku, tool-calling).

Ported in spirit from the original briefbot's dashboard agent: a synchronous
generator that drives a multi-turn tool-use loop and yields plain dict events
(`token`/`tool_start`/`tool_end`/`title`/`done`/`error`) for the SSE endpoint.

Differences from v1: scoped per user to bbv2's data, **Haiku** (not Opus), and a
non-streaming model call per turn (each turn's text is emitted as one `token`
event) — simpler and robust; true token streaming can be layered on later. The
model call, title generator, and summarizer are injectable for offline tests.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable, Iterator

from . import config
from .agent_tools import TOOL_SCHEMAS
from .cluster import cluster_items
from .llm import LLMError, anthropic_messages, generate_text
from .store import Store
from .usage import SYSTEM_USER_ID, budget_status, meter_usage, metered_generate

MAX_ITERATIONS = 8
MAX_RESULT_CHARS = 8000

# Canned first-visit greeting — shown (as if Briefbot said it) on a user's very
# first chat, and prepended to the agent's context on their first message so the
# model has continuity. Single source: the dashboard `/me` serves this exact text.
GREETING = (
    "Hi, I'm **Briefbot** 👋 — your personal news assistant. Tell me what you're "
    "interested in and we'll find some topics to follow to get your news stream "
    "flowing. You can also ask me to search your stories or summarize an article "
    "or paper anytime."
)

def _system_prompt() -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return (
        "You are Briefbot, a research assistant embedded in a personal news "
        "dashboard. You help the user explore their subscribed news stories and "
        "manage favorites.\n\n"
        f"Today is {today}.\n\n"
        "Ground every factual answer in the tools — never invent stories, titles, "
        "or links. Call tools as needed (you may call several) before answering. "
        "When you reference a story, include its markdown link. Prefer "
        "summarize_article when asked to explain a specific article. Be concise "
        "and conversational; use short markdown. If nothing relevant is found, say so.\n\n"
        "When the user wants to follow a NEW subject, you can create a topic with "
        "create_topic. First confirm scope in your own words — e.g. 'So this topic "
        "should cover news about cryptocurrencies and related markets?' — and only "
        "call create_topic once they say yes. Provisioning runs automatically and may "
        "take a moment; after it finishes, tell them it's ready and they're subscribed. "
        "To follow a topic that ALREADY exists on the platform, use subscribe_topic "
        "(no need to re-create it).\n\n"
        "Personalize using the user context block below:\n"
        "- If they have NO subscriptions, warmly help them get started: ask what "
        "subjects interest them, then set those up with create_topic. If their "
        "interests match topics already on the platform, offer those via "
        "subscribe_topic as a quick shortcut.\n"
        "- If they DO have subscriptions, open by surfacing what's going on in their "
        "stories (use get_trending / search_stories), discuss it, and suggest further "
        "topics — existing platform ones (subscribe_topic) or new ones (create_topic).\n"
        "- Be mindful of the token budget shown below: keep replies tight, and if "
        "they're running low, mention it briefly.\n\n"
        "About the Headlines page: the create_topic result includes `headline_ready`. "
        "When it is TRUE, the topic's Headlines summary was just built — tell the user "
        "their Headlines is ready now and invite them to open it. When it is FALSE "
        "(an established user past initial setup), do NOT promise an instant update: "
        "explain that the topic's **rundown** updates as soon as they open the topic, "
        "and the **next daily brief** (built automatically overnight) will include it "
        "in their morning Headlines from then on. Never tell a user setting up their "
        "first topics that they must wait until tomorrow — those are ready now."
    )


def _context_block(store: Store, user_id: int) -> str:
    """Per-turn user context appended to the system prompt (no extra LLM call):
    subscriptions, other available platform topics, and token-budget status."""
    subs = store.user_subscriptions(user_id)
    sub_names = [t["name"] for t in subs]
    sub_slugs = {t["slug"] for t in subs}
    available = [t["name"] for t in store.list_topics() if t["slug"] not in sub_slugs]

    st = budget_status(store, user_id)
    used, limit = int(st["used"]), int(st["limit"])
    remaining = max(0, limit - used)

    lines = ["\n\n--- Current user context ---"]
    if sub_names:
        lines.append(f"Subscriptions ({len(sub_names)}): {', '.join(sub_names)}.")
    else:
        lines.append("Subscriptions: NONE yet — they haven't set up any topics.")
    if available:
        shown = available[:20]
        more = "" if len(available) <= 20 else f" (+{len(available) - 20} more)"
        lines.append(
            f"Other topics already on the platform they could subscribe to: "
            f"{', '.join(shown)}{more}."
        )
    lines.append(
        f"Token budget today: {used:,} / {limit:,} used (~{remaining:,} left)."
    )
    return "\n".join(lines)


# ---- tool execution ----------------------------------------------------------

def _items_from_rows(rows: list[Any]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def _fetch_text(url: str, max_chars: int = 6000) -> str:
    if not url:
        return ""
    try:
        from bs4 import BeautifulSoup

        from .safefetch import safe_get

        r = safe_get(
            url, timeout=15, headers={"User-Agent": config.USER_AGENT}
        )
        if r.status_code >= 400:
            return ""
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        return " ".join(soup.get_text(" ").split())[:max_chars]
    except Exception:
        return ""


def _resolve_folder_id(store: Store, user_id: int, name: str | None) -> str:
    return store.create_folder(user_id, (name or "favorites").strip() or "favorites")


def execute_tool(
    store: Store,
    user_id: int,
    name: str,
    args: dict[str, Any],
    summarize_generate: Callable[..., str],
) -> tuple[Any, str]:
    """Run a tool; returns (result, short_summary)."""
    args = args or {}
    if name == "search_stories":
        rows = store.query_stories(
            user_id,
            search=(args.get("query") or "").strip() or None,
            limit=int(args.get("limit") or 15),
        )
        items = [
            {
                "title": r["title"],
                "url": r["url"],
                "source_name": r["source_name"],
                "published_at": r["published_at"],
            }
            for r in rows
        ]
        return {"items": items}, f"{len(items)} stories"

    if name == "get_trending":
        rows = store.items_for_user(user_id, limit=120)
        clusters = cluster_items(_items_from_rows(rows))[: int(args.get("limit") or 8)]
        trend = [
            {
                "label": c["label"],
                "item_count": c["item_count"],
                "representative_title": c["representative_title"],
                "representative_url": c["representative_url"],
            }
            for c in clusters
        ]
        return {"trending": trend}, f"{len(trend)} storylines"

    if name == "summarize_article":
        rows = store.query_stories(user_id, search=(args.get("query") or "").strip() or None, limit=1)
        if not rows:
            return {"error": f"no story matched: {args.get('query')}"}, "no match"
        s = rows[0]
        text = _fetch_text(s["url"] or "") or (s["summary"] or "")
        if not text:
            return {"title": s["title"], "url": s["url"], "error": "no readable content"}, "no content"
        prompt = (
            "Summarize this article in 4-6 sentences for a busy reader. Be faithful "
            f"to the text; do not invent facts.\n\nTitle: {s['title']}\n\n{text}"
        )
        try:
            summary_md = summarize_generate(prompt, max_tokens=500, temperature=0.2)
        except LLMError as exc:
            return {"title": s["title"], "url": s["url"], "error": str(exc)}, "summary failed"
        return (
            {
                "title": s["title"],
                "url": s["url"],
                "source_name": s["source_name"],
                "summary_md": summary_md,
            },
            f"summarized '{s['title']}'",
        )

    if name == "subscribe_topic":
        q = (args.get("name") or args.get("slug") or "").strip()
        if not q:
            return {"error": "topic name required"}, "missing name"
        topic = store.get_topic(q) or store.get_topic(_slugify(q))
        if not topic:
            return (
                {"error": f"no existing topic '{q}' — use create_topic to make one"},
                "no such topic",
            )
        store.subscribe(user_id, int(topic["id"]))
        return (
            {"subscribed": True, "slug": topic["slug"], "name": topic["name"]},
            f"subscribed to {topic['name']}",
        )

    if name == "list_folders":
        folders = [{"name": f["name"], "count": f["count"]} for f in store.list_folders(user_id)]
        return {"folders": folders}, f"{len(folders)} folders"

    if name == "create_folder":
        nm = (args.get("name") or "").strip()
        if not nm:
            return {"error": "folder name required"}, "missing name"
        store.create_folder(user_id, nm)
        return {"folder": nm, "created": True}, f"folder '{nm}' ready"

    if name == "add_favorite":
        title = (args.get("title") or "").strip()
        url = (args.get("url") or "").strip()
        item_id = None
        query = (args.get("query") or "").strip()
        if query and not url:
            rows = store.query_stories(user_id, search=query, limit=1)
            if rows:
                title = rows[0]["title"] or title
                url = rows[0]["url"] or url
                item_id = rows[0]["item_id"]
        if not url:
            return {"error": f"could not find an article for: {query or '(none)'}"}, "not found"
        fid = _resolve_folder_id(store, user_id, args.get("folder"))
        store.add_favorite(user_id, fid, title or url, url, item_id)
        folder_name = (args.get("folder") or "favorites").strip() or "favorites"
        return {"saved": True, "folder": folder_name, "title": title or url}, f"saved to '{folder_name}'"

    if name == "list_favorites":
        folder_name = (args.get("folder") or "favorites").strip() or "favorites"
        folder = store.get_folder_by_name(user_id, folder_name)
        if not folder:
            return {"error": f"no folder named '{folder_name}'"}, "folder not found"
        items = [
            {"title": r["title"], "url": r["url"]}
            for r in store.list_favorites(user_id, folder["id"])
        ]
        return {"folder": folder_name, "items": items}, f"{len(items)} in '{folder_name}'"

    if name == "remove_favorite":
        folder_name = (args.get("folder") or "favorites").strip() or "favorites"
        folder = store.get_folder_by_name(user_id, folder_name)
        if not folder:
            return {"error": f"no folder named '{folder_name}'"}, "folder not found"
        url = (args.get("url") or "").strip()
        query = (args.get("query") or "").strip()
        if not url and query:
            rows = store.query_stories(user_id, search=query, limit=1)
            if rows:
                url = rows[0]["url"] or ""
        target = next(
            (r for r in store.list_favorites(user_id, folder["id"]) if r["url"] == url), None
        )
        if not target:
            return {"error": f"not saved in '{folder_name}'"}, "not in folder"
        store.remove_favorite(user_id, target["id"])
        return {"removed": True, "folder": folder_name, "url": url}, f"removed from '{folder_name}'"

    return {"error": f"unknown tool: {name}"}, "unknown tool"


def _result_string(result: Any) -> str:
    text = json.dumps(result, ensure_ascii=True, default=str)
    return text if len(text) <= MAX_RESULT_CHARS else text[:MAX_RESULT_CHARS] + "\n…(truncated)"


def _history(store: Store, conversation_id: str) -> list[dict[str, Any]]:
    msgs: list[dict[str, Any]] = []
    for row in store.get_messages(conversation_id):
        role = row["role"]
        content = (row["content"] or "").strip()
        if role in {"user", "assistant"} and content:
            msgs.append({"role": role, "content": content})
    return msgs


def _default_title(user_text: str, generate: Callable[..., str] = generate_text) -> str:
    prompt = (
        "Write a short, specific title (max 6 words) for a chat starting with this "
        "message. Return only the title.\n\n"
        f"Message: {user_text}"
    )
    try:
        title = generate(prompt, max_tokens=24, temperature=0.2).strip()
    except Exception:
        title = ""
    title = title.strip().strip("\"'`").splitlines()[0] if title else ""
    return (title or (user_text or "New chat").strip())[:80]


def _slugify(name: str) -> str:
    out = "".join(c if c.isalnum() else "-" for c in (name or "").lower())
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")[:40]


def _create_topic_events(
    store: Store,
    user_id: int,
    args: dict[str, Any],
    *,
    moderate_generate: Callable[..., str] | None,
    review_generate: Callable[..., str] | None,
) -> Iterator[dict[str, Any]]:
    """Create + provision a topic, streaming `topic_stage` events into the chat.

    Yields a `tool_start`, then a `topic_stage` per provisioning step, then a
    `tool_end`; returns `(result, summary)` for the model's tool_result. The
    hard token budget gates this (provisioning is the expensive path)."""
    from .moderation import ModerationError, moderate_topic
    from .provision import provision_topic

    name = (args.get("name") or "").strip()
    if not name:
        return {"error": "a topic name is required"}, "missing name"

    gate = budget_status(store, user_id)
    if not gate["allowed"]:
        return {"error": gate["message"], "limit_reached": True}, "limit reached"

    # Meter the moderation LLM call to the acting user (tests inject a stub).
    mod_gen = moderate_generate or metered_generate(store, user_id, "moderation")
    try:
        clean = moderate_topic(
            _slugify(name),
            name,
            mod_gen,
            fail_closed=config.moderation_fail_closed(),
        )
    except ModerationError as exc:
        return {"error": f"topic rejected: {exc.reason}"}, "rejected"
    slug, display = clean["slug"], clean["name"]
    store.add_topic(slug, display, (args.get("description") or "").strip())

    yield {"type": "tool_start", "name": "create_topic"}
    last_stage: str | None = None
    sources = items = dropped = 0
    # Build a brief during provisioning while the user is still in their initial
    # setup window (account age — reload-proof), so every topic they add then
    # populates the first Headlines. After it, new topics defer to the nightly job
    # + on-demand rundown (no per-add LLM cost). System bucket (shared artifact).
    building_brief = store.is_recent_user(
        user_id, config.onboard_brief_window_min() * 60
    )
    brief_generate = (
        metered_generate(store, SYSTEM_USER_ID, "rundown") if building_brief else None
    )
    for ev in provision_topic(
        store, slug, review_generate=review_generate, brief_generate=brief_generate
    ):
        if ev.get("type") == "stage":
            last_stage = str(ev.get("stage"))
            yield {"type": "topic_stage", "slug": slug, "name": display, "stage": last_stage}
            if ev.get("stage") == "ready":
                sources = int(ev.get("sources") or 0)
                items = int(ev.get("items") or 0)
                dropped = int(ev.get("dropped") or 0)
        elif ev.get("type") == "error":
            yield {
                "type": "topic_stage",
                "slug": slug,
                "name": display,
                "stage": last_stage,
                "failed": True,
            }
            yield {"type": "tool_end", "name": "create_topic", "summary": "provisioning failed"}
            return {"error": ev.get("message"), "slug": slug}, "provisioning failed"

    store.subscribe(user_id, int(store.get_topic(slug)["id"]))
    summary = f"created '{display}' — {sources} sources, {items} stories"
    yield {"type": "tool_end", "name": "create_topic", "summary": summary}
    return (
        {
            "created": True,
            "slug": slug,
            "name": display,
            "subscribed": True,
            "sources": sources,
            "stories": items,
            "dropped": dropped,
            # True → the topic's Headlines summary was built now (initial setup).
            # False → it'll appear in the next overnight brief; its rundown updates
            # when the user opens the topic.
            "headline_ready": building_brief,
        },
        summary,
    )


# ---- the turn ----------------------------------------------------------------

def run_chat_turn(
    store: Store,
    user_id: int,
    conversation_id: str,
    user_text: str,
    *,
    call_model: Callable[..., dict[str, Any]] | None = None,
    title_fn: Callable[[str], str] | None = None,
    summarize_generate: Callable[..., str] | None = None,
    moderate_generate: Callable[..., str] | None = None,
    review_generate: Callable[..., str] | None = None,
) -> Iterator[dict[str, Any]]:
    """Drive one chat turn, yielding SSE event dicts. Persists the user message,
    the tool-augmented assistant reply, and (on the first turn) a generated title.
    Meters every LLM call against the user's daily token budget; the soft (chat)
    tier gates this turn before any model call is made."""
    call_model = call_model or anthropic_messages
    metered = metered_generate(store, user_id, "chat")
    title_fn = title_fn or (lambda text: _default_title(text, generate=metered))
    summarize_generate = summarize_generate or metered

    conv = store.get_conversation(user_id, conversation_id)
    if not conv:
        yield {"type": "error", "message": "conversation not found"}
        return

    gate = budget_status(store, user_id)
    if not gate["allowed"]:
        yield {"type": "error", "message": gate["message"]}
        return

    needs_title = not (conv["title"] or "").strip()
    # First message of the user's first-ever conversation → **persist** the canned
    # greeting as the conversation's first message, so it stays in the thread (live
    # and on reload) and seeds the model's context naturally from "what are you
    # into?".
    first_ever = (
        not store.get_messages(conversation_id)
        and len(store.list_conversations(user_id)) <= 1
    )
    if first_ever:
        store.append_message(conversation_id, user_id, "assistant", GREETING)
    store.append_message(conversation_id, user_id, "user", user_text)
    messages = _history(store, conversation_id)
    system = _system_prompt() + _context_block(store, user_id)

    assistant_text = ""
    tool_log: list[dict[str, Any]] = []

    for _ in range(MAX_ITERATIONS):
        try:
            resp = call_model(messages, tools=TOOL_SCHEMAS, system=system)
        except LLMError as exc:
            yield {"type": "error", "message": str(exc)}
            return
        meter_usage(store, user_id, "chat", resp.get("usage"), resp.get("model"))
        blocks = resp.get("content") or []
        stop = resp.get("stop_reason")

        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
        if text:
            yield {"type": "token", "text": text}
            assistant_text += ("\n\n" if assistant_text else "") + text

        messages.append({"role": "assistant", "content": blocks})
        if stop != "tool_use":
            break

        tool_results = []
        for b in blocks:
            if b.get("type") != "tool_use":
                continue
            name = b.get("name") or ""
            args = b.get("input") or {}
            if name == "create_topic":
                # Streams its own tool_start/topic_stage/tool_end events.
                result, summary = yield from _create_topic_events(
                    store,
                    user_id,
                    args,
                    moderate_generate=moderate_generate,
                    review_generate=review_generate,
                )
            else:
                yield {"type": "tool_start", "name": name}
                result, summary = execute_tool(store, user_id, name, args, summarize_generate)
                yield {"type": "tool_end", "name": name, "summary": summary}
            tool_log.append({"name": name, "summary": summary})
            tool_results.append(
                {"type": "tool_result", "tool_use_id": b.get("id"), "content": _result_string(result)}
            )
        messages.append({"role": "user", "content": tool_results})
    else:
        note = "\n\n_(Stopped after the tool-call limit.)_"
        assistant_text += note
        yield {"type": "token", "text": note}

    final = (assistant_text or "_(No response.)_").strip()
    store.append_message(conversation_id, user_id, "assistant", final, tool_calls=tool_log or None)
    store.touch_conversation(conversation_id)
    store.record_usage(user_id, "chat-turn", None, 0, 0, interaction=1)

    if needs_title:
        title = title_fn(user_text)
        store.set_conversation_title(user_id, conversation_id, title)
        yield {"type": "title", "title": title}

    yield {"type": "done", "conversation_id": conversation_id}
