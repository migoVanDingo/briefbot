import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import AddIcon from "@mui/icons-material/Add";
import SendIcon from "@mui/icons-material/Send";
import PersonIcon from "@mui/icons-material/PersonOutlined";
import BotIcon from "@mui/icons-material/SmartToyOutlined";
import {
  api,
  type ChatMessage,
  type ConversationMeta,
  type ProvisionRun,
  type UsageStats,
} from "../api";
import { useToasts } from "../state/toasts";
import { useAuth } from "../state/auth";
import { useProvisioning } from "../lib/useProvisioning";
import { useDiscoveries } from "../lib/useDiscoveries";
import { ProvisionPipeline } from "../components/ProvisionPipeline";
import { DiscoveryCard } from "../components/DiscoveryCard";
import { LoadingBanner } from "../components/LoadingBanner";
import { Markdown } from "../components/Markdown";
import { DISCOVER_PHRASES, COLLECT_PHRASES } from "../lib/phrases";

// The witty cycling phrases shown while a topic provisions in-chat (the best part).
const PROVISION_PHRASES = [...DISCOVER_PHRASES, ...COLLECT_PHRASES];

// Show the "view headlines" link once provisioning is done: a run finished (0023)
// or — for old conversations whose runs have aged out — a create_topic tool ran.
function provisioningDone(m: ChatMessage, msgRuns: ProvisionRun[]): boolean {
  const live =
    msgRuns.length > 0 &&
    msgRuns.every((r) => r.status !== "running") &&
    msgRuns.some((r) => r.status === "done");
  const persisted = !!m.tool_calls?.some((t) => t.name === "create_topic");
  return live || persisted;
}

// Remember the last-opened conversation so returning to /chat restores it instead
// of a blank new chat. Validated against the user's own list, so it's safe even if
// browsers are shared (a stale/foreign id just falls back to the latest chat).
const LAST_CHAT_KEY = "bbv2.lastChat";
const readLastChat = (): string | null => {
  try {
    return localStorage.getItem(LAST_CHAT_KEY);
  } catch {
    return null;
  }
};

export function Chat() {
  const push = useToasts((s) => s.push);
  const greeting = useAuth((s) => s.profile?.greeting ?? "");
  const [convos, setConvos] = useState<ConversationMeta[]>([]);
  const [activeId, setActiveId] = useState<string>("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [usage, setUsage] = useState<UsageStats | null>(null);
  const threadEnd = useRef<HTMLDivElement>(null);
  const streamAbort = useRef<AbortController | null>(null);
  // Latest selected conversation id, readable inside async callbacks without a
  // stale closure — guards against a slow getConversation landing after a switch.
  const activeRef = useRef("");
  activeRef.current = activeId;
  // Provisioning pipelines for this conversation, polled from the server (0023) so
  // they survive refresh/navigation. Rendered inline against their message id.
  const { runs, refresh: refreshRuns } = useProvisioning(activeId || undefined);
  const { runs: discoveryRuns, refresh: refreshDiscoveries } = useDiscoveries(
    activeId || undefined,
  );

  // Abort an in-flight chat stream if the user navigates away mid-turn, so the
  // reader stops and we don't setState on an unmounted component.
  useEffect(() => () => streamAbort.current?.abort(), []);

  const rememberActive = (id: string) => {
    setActiveId(id);
    try {
      localStorage.setItem(LAST_CHAT_KEY, id);
    } catch {
      /* private mode — non-critical */
    }
  };

  const loadConvos = async () => {
    try {
      setConvos(await api.listConversations());
    } catch (e) {
      push(String(e), "error");
    }
  };

  const loadUsage = async () => {
    try {
      setUsage(await api.usage());
    } catch {
      /* non-critical — counter just stays as-is */
    }
  };

  useEffect(() => {
    // Restore the last-accessed chat (or the most recent one) instead of a blank.
    (async () => {
      let list: ConversationMeta[] = [];
      try {
        list = await api.listConversations();
        setConvos(list);
      } catch (e) {
        push(String(e), "error");
      }
      const lastId = readLastChat();
      const restore = list.find((c) => c.id === lastId) ?? list[0];
      if (restore) select(restore.id);
    })();
    loadUsage();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    threadEnd.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const select = async (id: string) => {
    rememberActive(id);
    setMessages([]);
    try {
      const c = await api.getConversation(id);
      // Guard against a slow load for a conversation the user already switched away
      // from — only apply if this id is still the active one.
      if (activeRef.current === id) setMessages(c.messages);
    } catch (e) {
      push(String(e), "error");
    }
  };

  const newChat = async () => {
    try {
      const c = await api.createConversation();
      await loadConvos();
      rememberActive(c.id);
      setMessages([]);
    } catch (e) {
      push(String(e), "error");
    }
  };

  const send = async (e: React.FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || sending) return;

    let cid = activeId;
    if (!cid) {
      try {
        cid = (await api.createConversation()).id;
        rememberActive(cid);
      } catch (err) {
        push(String(err), "error");
        return;
      }
    }

    // On the user's first-ever message, pin the canned greeting as the first
    // bubble (the server persists the same text, so it survives a reload too).
    const isFirstEver = convos.length === 0 && messages.length === 0;
    setInput("");
    setMessages((m) => [
      ...(isFirstEver && greeting
        ? [{ role: "assistant" as const, content: greeting }]
        : []),
      ...m,
      { role: "user", content: text },
      { role: "assistant", content: "", tool_calls: [] },
    ]);
    setSending(true);

    const patchLast = (fn: (m: ChatMessage) => ChatMessage) =>
      setMessages((prev) => {
        const copy = prev.slice();
        copy[copy.length - 1] = fn(copy[copy.length - 1]);
        return copy;
      });

    streamAbort.current = new AbortController();
    try {
      await api.streamMessage(cid, text, (ev) => {
        const type = ev.type as string;
        if (type === "token") {
          patchLast((m) => ({ ...m, content: m.content + (ev.text as string) }));
        } else if (type === "tool_start") {
          patchLast((m) => ({
            ...m,
            tool_calls: [...(m.tool_calls || []), { name: ev.name as string, summary: "…" }],
          }));
        } else if (type === "tool_end") {
          patchLast((m) => {
            const tc = (m.tool_calls || []).slice();
            for (let i = tc.length - 1; i >= 0; i--) {
              if (tc[i].name === ev.name && tc[i].summary === "…") {
                tc[i] = { name: ev.name as string, summary: ev.summary as string };
                break;
              }
            }
            return { ...m, tool_calls: tc };
          });
        } else if (type === "message") {
          // The server pre-minted this assistant message's id; tag the live bubble
          // so polled runs (below) attach to it (and re-hydrate on reload).
          patchLast((m) => ({ ...m, id: ev.id as string }));
        } else if (type === "topic_run") {
          // A background provision run started — fetch it now so the pill appears
          // immediately, then the hook keeps polling it forward.
          refreshRuns();
        } else if (type === "search_run") {
          // A background source search started — fetch it so the results card
          // appears, then the hook polls it to completion (0030).
          refreshDiscoveries();
        } else if (type === "title") {
          setConvos((cs) =>
            cs.map((c) => (c.id === cid ? { ...c, title: ev.title as string } : c)),
          );
        } else if (type === "error") {
          push(String(ev.message), "error");
        }
      }, streamAbort.current.signal);
    } catch (err) {
      if (streamAbort.current?.signal.aborted) return; // unmounted — ignore
      push(String(err), "error");
    } finally {
      if (!streamAbort.current?.signal.aborted) {
        setSending(false);
        loadConvos();
        loadUsage();
        refreshRuns(); // keep polling any pipeline this turn kicked off
        refreshDiscoveries(); // …and any source search
      }
    }
  };

  return (
    <div className="chat-shell">
      <aside className="chat-side">
          <button className="btn primary chat-new icon-btn-text" onClick={newChat}>
            <AddIcon fontSize="small" />
            New chat
          </button>
          <ul className="convo-list">
            {convos.map((c) => (
              <li key={c.id}>
                <button
                  className={`convo-item${activeId === c.id ? " active" : ""}`}
                  onClick={() => select(c.id)}
                >
                  {c.title || "New chat"}
                </button>
              </li>
            ))}
            {convos.length === 0 && (
              <li className="muted small pad">No chats yet.</li>
            )}
          </ul>
          {usage && (
            <div className="usage-meter">
              <div className="usage-row">
                <span>Interactions</span>
                <b>{usage.interactions}</b>
              </div>
              {usage.enabled && (
                <>
                  <div className="usage-row">
                    <span>Tokens today</span>
                    <b>
                      {usage.tokens_used.toLocaleString()} /{" "}
                      {usage.limit.toLocaleString()}
                    </b>
                  </div>
                  <div className="usage-bar">
                    <span
                      className={`usage-fill${usage.blocked ? " over" : ""}`}
                      style={{
                        width: `${Math.min(100, (usage.tokens_used / usage.limit) * 100)}%`,
                      }}
                    />
                  </div>
                  {usage.blocked && (
                    <div className="usage-blocked">
                      Daily limit reached — resets in{" "}
                      {Math.max(1, Math.round(usage.resets_in / 3600))}h.
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </aside>

        <section className="chat-main">
          <div className="thread">
            {messages.length === 0 ? (
              convos.length === 0 && greeting ? (
                // First-ever chat: a canned Briefbot greeting (no LLM call). The
                // server seeds the same text into the agent's context on the first
                // message. Later empty chats show the plain placeholder instead.
                <div className="msg-row assistant">
                  <span className="msg-avatar" aria-hidden="true">
                    <BotIcon fontSize="small" />
                  </span>
                  <div className="msg assistant">
                    <div className="msg-body">
                      <Markdown>{greeting}</Markdown>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="muted pad">
                  Ask about your stories — search, summarize an article, or manage
                  favorites.
                </div>
              )
            ) : (
              messages.map((m, i) => {
                const msgRuns = m.id ? runs.filter((r) => r.message_id === m.id) : [];
                const msgSearches = m.id
                  ? discoveryRuns.filter((r) => r.message_id === m.id)
                  : [];
                return (
                <div key={m.id ?? i} className={`msg-row ${m.role}`}>
                  <span className="msg-avatar" aria-hidden="true">
                    {m.role === "user" ? (
                      <PersonIcon fontSize="small" />
                    ) : (
                      <BotIcon fontSize="small" />
                    )}
                  </span>
                  <div className={`msg ${m.role}`}>
                    {m.tool_calls && m.tool_calls.length > 0 && (
                      <div className="tool-chips">
                        {m.tool_calls.map((t, j) => (
                          <span key={j} className="tool-chip">
                            {t.name}: {t.summary}
                          </span>
                        ))}
                      </div>
                    )}
                    {msgRuns.length > 0 && (
                      <div className="topic-runs">
                        {msgRuns.map((r) => (
                          <div key={r.id} className="topic-run">
                            <div className="topic-run-label">{r.name}</div>
                            <ProvisionPipeline stage={r.stage} failed={r.failed} />
                            {r.status === "running" && (
                              <LoadingBanner phrases={PROVISION_PHRASES} />
                            )}
                            {r.failed && r.error && (
                              <div className="muted small">{r.error}</div>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                    {msgSearches.map((r) => (
                      <DiscoveryCard key={r.id} run={r} onCommitted={refreshDiscoveries} />
                    ))}
                    <div className="msg-body">
                      {m.content ? (
                        m.role === "assistant" ? (
                          <Markdown>{m.content}</Markdown>
                        ) : (
                          m.content
                        )
                      ) : m.role === "assistant" && sending && !msgRuns.length ? (
                        "…"
                      ) : (
                        ""
                      )}
                    </div>
                    {m.role === "assistant" && provisioningDone(m, msgRuns) && (
                      <Link to="/headlines" className="headlines-link">
                        View your headlines →
                      </Link>
                    )}
                  </div>
                </div>
                );
              })
            )}
            <div ref={threadEnd} />
          </div>

          <form className="chat-input" onSubmit={send}>
            <input
              placeholder={
                usage?.blocked
                  ? "Daily limit reached…"
                  : "Message briefbot…"
              }
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={sending || usage?.blocked}
            />
            <button
              className="btn primary icon-btn-text"
              type="submit"
              disabled={sending || !input.trim() || usage?.blocked}
            >
              <SendIcon fontSize="small" />
              {sending ? "…" : "Send"}
            </button>
          </form>
        </section>
    </div>
  );
}
