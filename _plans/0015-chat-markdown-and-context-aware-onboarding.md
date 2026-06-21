# 0015 — Chat markdown rendering + a context-aware, onboarding agent

**Status:** ✅ Implemented (2026-06-20)
**Date:** 2026-06-20
**Phase:** Build · **Depends on:** [0012](./0012-chat-topic-creation-and-token-budget.md) (agent + budget), [0014](./0014-first-visit-flow-brief-generation-and-cadence.md) (onboarding + rundowns)

> **Shipped (all phases):** P1 chat **markdown** rendering (`react-markdown` +
> `remark-gfm`, safe links, `.md` styles) · P2 **context-aware agent** —
> `_context_block` injects the user's subscriptions, token used/limit, and other
> available platform topics each turn; system prompt gained onboarding/
> personalization rules; new **`subscribe_topic`** tool (follow an existing topic
> instantly) · P3 canned first **`GREETING`** (single source in `agent.py`, served
> via `/me`) shown only on the first-ever chat and **prepended to the agent's
> context** on the first message. 102 pytest pass; dashboard build clean.
> `agent.py` schemas split into `agent_tools.py` for the 600-line cap.

## Problem

1. **Markdown renders raw.** The agent is told to "use short markdown," but the chat
   renders message text literally (`.msg-body` = plain text + `pre-wrap`), so users
   see stray `*` / `#` / `**`. `react-markdown` isn't installed.
2. **Briefbot doesn't open the conversation.** On first login nothing greets the
   user; they have to guess what to do. The agent only reacts.
3. **The system prompt is context-blind.** It knows nothing about the user's
   **subscriptions**, **token usage/limit**, or **what topics exist** — so it can't
   onboard a new user, discuss an existing user's stories, or suggest topics.

## A. Render markdown in chat

- Add **`react-markdown`** (+ `remark-gfm` for lists/tables/strikethrough). Render
  **assistant** messages through it; keep user messages plain (their own text).
- Links open in a new tab (`rel="noreferrer"`), and we constrain to safe nodes (no
  raw HTML). Style headings/lists/code/links to match the app tokens.
- The canned intro and any tool-chip text stay as-is. Briefs/rundowns already split
  paragraphs; optionally route their summary through the same renderer later.

## B. Inject user context into the system prompt

Build a **context block** in `run_chat_turn` (cheap, no extra LLM call) and prepend
it to `_system_prompt()` each turn:

- **Subscriptions:** the user's topic names (and slugs), or "none yet."
- **Token budget:** `used / limit` for the day + roughly how much is left, so
  Briefbot is **aware of usage** and can be concise / mention it when low.
- **Available topics:** platform topics the user is **not** subscribed to (from
  `store.list_topics()` minus subscriptions) — so "suggest existing topics" is
  grounded in real ones, not invented.

This is data the server already has; it just isn't told to the model today.

## C. Onboarding + personalization behavior (system-prompt rules)

Extend the prompt so Briefbot **drives** based on the injected context:

- **No subscriptions →** warmly onboard: "Let's set up some topics so your news
  starts flowing — what are you interested in?" Gather interests, then confirm and
  `create_topic` (0012 flow). Offer relevant **existing** platform topics to
  subscribe to as a shortcut.
- **Has subscriptions →** open by discussing **what's going on**: use
  `get_trending` / `search_stories` to surface current storylines, talk through
  them, and from the conversation **suggest more topics** — existing platform ones
  to subscribe to, or new searchable ones to create.
- **Always:** be token-aware (concise; note remaining budget if it's getting low),
  and ground every claim in tools (unchanged).

## D. First greeting — canned, then fed into context (resolved)

**No LLM greeting.** On a user's **first true visit only** (`onboarded` false, empty
thread), the chat shows a **canned** message rendered as if Briefbot said it — it
introduces itself and invites the user to share interests (e.g. "Hi, I'm Briefbot
👋 — tell me what you're into and we'll find some topics to get your news flowing.").
It is **not** an LLM call and **not** a persisted turn.

When the user sends their **next message**, that canned intro is **prepended to the
agent's context** for that turn (a synthetic leading assistant message), so Briefbot
has continuity — it knows it just introduced itself and asked what they're into and
can pick up the thread naturally.

**Subsequent new chats are empty** — the canned intro shows **only on the first true
visit**, never on later empty threads. Once `onboarded`, the normal empty-state
placeholder applies.

Implementation notes:
- The canned text is the **single source** in the backend (`agent.py`) so the
  context injection and the displayed text can't drift; the client renders the same
  string for the first-visit bubble (or the server seeds it — see below).
- Injection: in `run_chat_turn`, when the user is **not onboarded** and this is the
  **first user message** of the conversation, prepend the canned intro as a leading
  `assistant` message in the model `messages` (persist optional; context is the
  requirement).
- Also **fix the current canned intro not surfacing** — verify the
  `onboarded`/empty-thread render path on a fresh first login.

## Decisions — all resolved

1. Greeting = **canned, no LLM call** (D2 shape, but seeded by the backend so it
   reaches the agent's context).
2. Token metering — **n/a** (no greeting call).
3. Re-greeting — **only on the first true visit**; subsequent new chats are empty.

## Phasing

- **P1 — markdown rendering** (small, isolated; fixes the visible bug).
- **P2 — context block + system-prompt rules** (B + C): the brains of the onboarding.
- **P3 — canned first greeting + context injection** (D).

## Done when

Chat renders real markdown (no stray `*`/`#`); a first-time user is greeted by a
canned Briefbot intro that the agent then has in context; Briefbot adapts to the
injected context — guiding a subscription-less user to set up topics, or discussing
stories and suggesting topics for a subscribed one — and is aware of the user's
subscriptions and token budget throughout. Later empty chats show no canned intro.

## Out of scope / later

- Streaming token-by-token rendering (still one `token` event per turn, 0008).
- Embedding-based topic suggestions (needs the persistent-clusters workstream).
