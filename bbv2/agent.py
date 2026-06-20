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

import requests

from . import config
from .cluster import cluster_items
from .llm import LLMError, anthropic_messages, generate_text
from .store import Store

MAX_ITERATIONS = 8
MAX_RESULT_CHARS = 8000

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "search_stories",
        "description": "Search the user's subscribed stories by free-text query. "
        "Returns matching items (title, url, source). Empty query lists the latest.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search terms (may be empty)."},
                "limit": {"type": "integer", "description": "Max results (default 15)."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_trending",
        "description": "Top trending storylines across the user's subscriptions, "
        "by recent momentum.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max storylines (default 8)."}
            },
            "required": [],
        },
    },
    {
        "name": "summarize_article",
        "description": "Find the best-matching subscribed story for a query, fetch "
        "it, and return a grounded summary. Use when asked to summarize/explain an article.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Title or topic of the article."}
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_folders",
        "description": "List the user's favorites folders and how many links each holds.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "create_folder",
        "description": "Create a favorites folder by name (idempotent).",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "add_favorite",
        "description": "Save a story to a favorites folder. Identify it by `query` "
        "(a title/topic to locate it) or explicit `url`+`title`. `folder` defaults to "
        "'favorites' and is created if missing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "url": {"type": "string"},
                "title": {"type": "string"},
                "folder": {"type": "string"},
            },
            "required": [],
        },
    },
    {
        "name": "list_favorites",
        "description": "List saved links in a favorites folder (default 'favorites').",
        "input_schema": {
            "type": "object",
            "properties": {"folder": {"type": "string"}},
            "required": [],
        },
    },
    {
        "name": "remove_favorite",
        "description": "Remove a saved link from a folder, by `query` or explicit `url`.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "url": {"type": "string"},
                "folder": {"type": "string"},
            },
            "required": [],
        },
    },
]


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
        "and conversational; use short markdown. If nothing relevant is found, say so."
    )


# ---- tool execution ----------------------------------------------------------

def _items_from_rows(rows: list[Any]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def _fetch_text(url: str, max_chars: int = 6000) -> str:
    if not url:
        return ""
    try:
        from bs4 import BeautifulSoup

        r = requests.get(url, timeout=15, headers={"User-Agent": config.USER_AGENT})
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


def _default_title(user_text: str) -> str:
    prompt = (
        "Write a short, specific title (max 6 words) for a chat starting with this "
        "message. Return only the title.\n\n"
        f"Message: {user_text}"
    )
    try:
        title = generate_text(prompt, max_tokens=24, temperature=0.2).strip()
    except Exception:
        title = ""
    title = title.strip().strip("\"'`").splitlines()[0] if title else ""
    return (title or (user_text or "New chat").strip())[:80]


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
) -> Iterator[dict[str, Any]]:
    """Drive one chat turn, yielding SSE event dicts. Persists the user message,
    the tool-augmented assistant reply, and (on the first turn) a generated title."""
    call_model = call_model or anthropic_messages
    title_fn = title_fn or _default_title
    summarize_generate = summarize_generate or generate_text

    conv = store.get_conversation(user_id, conversation_id)
    if not conv:
        yield {"type": "error", "message": "conversation not found"}
        return

    needs_title = not (conv["title"] or "").strip()
    store.append_message(conversation_id, user_id, "user", user_text)
    messages = _history(store, conversation_id)
    system = _system_prompt()

    assistant_text = ""
    tool_log: list[dict[str, Any]] = []

    for _ in range(MAX_ITERATIONS):
        try:
            resp = call_model(messages, tools=TOOL_SCHEMAS, system=system)
        except LLMError as exc:
            yield {"type": "error", "message": str(exc)}
            return
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

    if needs_title:
        title = title_fn(user_text)
        store.set_conversation_title(user_id, conversation_id, title)
        yield {"type": "title", "title": title}

    yield {"type": "done", "conversation_id": conversation_id}
