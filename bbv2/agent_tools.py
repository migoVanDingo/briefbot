"""Tool schemas for the bbv2 chat agent (Anthropic tool-use definitions).

Split out of `agent.py` (which holds the turn loop + execution) to stay under the
size cap. `execute_tool` in `agent.py` dispatches on these `name`s.
"""

from __future__ import annotations

from typing import Any

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
        "description": "Fetch an article and return a grounded summary. Pass `url` to "
        "summarize a SPECIFIC article (e.g. one from a find_sources result, even if "
        "it isn't subscribed yet) — prefer this when you have the article's url. "
        "Otherwise pass `query` to find the best-matching subscribed story.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Title or topic of a subscribed article."},
                "url": {"type": "string", "description": "Direct article URL to fetch + summarize."},
                "title": {"type": "string", "description": "Optional title for a `url` article."},
            },
        },
    },
    {
        "name": "read_source",
        "description": "List a specific source's RECENT articles (titles + urls). Use "
        "when the user asks about a particular source — e.g. one from a find_sources "
        "result ('list articles from smokinggun.org') or one they're subscribed to. "
        "`source` can be a domain/name from the search results or a feed URL. After "
        "listing, you can summarize any of them with summarize_article(url=…).",
        "input_schema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Source domain/name or feed URL."},
                "limit": {"type": "integer", "description": "Max articles (default 15)."},
            },
            "required": ["source"],
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
    {
        "name": "subscribe_topic",
        "description": "Subscribe the user to a topic that ALREADY exists on the "
        "platform (see the available topics in the user context). Use this instead "
        "of create_topic when the topic already exists — it's instant and free. If "
        "no such topic exists, use create_topic.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The topic's name or slug."}
            },
            "required": ["name"],
        },
    },
    {
        "name": "create_topic",
        "description": "Create a new news topic and provision it (find sources, "
        "collect stories, review). This kicks off a multi-step pipeline and the user "
        "is auto-subscribed when it finishes. ONLY call this AFTER the user has "
        "explicitly confirmed the topic — first restate what the topic will cover and "
        "ask them to confirm; do not call it on the same turn they first mention it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Display name for the topic, e.g. 'Crypto'.",
                },
                "description": {
                    "type": "string",
                    "description": "Optional one-line scope, e.g. 'cryptocurrencies and related markets'.",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "find_sources",
        "description": "Search the WEB for NEW sources (RSS feeds + articles) on a "
        "specific subject the user wants to follow that isn't covered by their "
        "current stories — e.g. 'find journals on multimodal learning in K-12'. This "
        "starts a background web search; a results card with the found sources and "
        "their latest headlines appears in the chat. Use this when search_stories "
        "returns nothing relevant and the user wants sources/research on a topic. "
        "After the results appear you can discuss them — list a source's articles "
        "with read_source, summarize one with summarize_article(url=…) — and when the "
        "user confirms, commit_sources places them into the best topic (or a new one).",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search the web for, e.g. 'multimodal learning in K-12 students'.",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "commit_sources",
        "description": "Add the sources from the most recent find_sources search in "
        "this conversation to the user's topics. Call this ONLY after the user "
        "confirms they want to add the found sources. The sources are routed to the "
        "best-matching existing topic(s) by similarity, or a new topic if none fit. "
        "When you report the result: say WHERE they went, that their stories will "
        "appear in the MORNING BRIEF starting tomorrow (not today's — briefs are "
        "daily), and that the user can explore them right now via the Stories page "
        "or by asking you to search them. Relay the result's `note`.",
        "input_schema": {"type": "object", "properties": {}},
    },
]
