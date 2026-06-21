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
]
