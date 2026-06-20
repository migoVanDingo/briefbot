import { useEffect, useRef, useState } from "react";
import {
  api,
  type ChatMessage,
  type ConversationMeta,
} from "../api";
import { useToasts } from "../state/toasts";

export function Chat() {
  const push = useToasts((s) => s.push);
  const [convos, setConvos] = useState<ConversationMeta[]>([]);
  const [activeId, setActiveId] = useState<string>("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const threadEnd = useRef<HTMLDivElement>(null);

  const loadConvos = async () => {
    try {
      setConvos(await api.listConversations());
    } catch (e) {
      push(String(e), "error");
    }
  };

  useEffect(() => {
    loadConvos();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    threadEnd.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const select = async (id: string) => {
    setActiveId(id);
    setMessages([]);
    try {
      const c = await api.getConversation(id);
      setMessages(c.messages);
    } catch (e) {
      push(String(e), "error");
    }
  };

  const newChat = async () => {
    try {
      const c = await api.createConversation();
      await loadConvos();
      setActiveId(c.id);
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
        setActiveId(cid);
      } catch (err) {
        push(String(err), "error");
        return;
      }
    }

    setInput("");
    setMessages((m) => [
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
        } else if (type === "title") {
          setConvos((cs) =>
            cs.map((c) => (c.id === cid ? { ...c, title: ev.title as string } : c)),
          );
        } else if (type === "error") {
          push(String(ev.message), "error");
        }
      });
    } catch (err) {
      push(String(err), "error");
    } finally {
      setSending(false);
      loadConvos();
    }
  };

  return (
    <div className="page">
      <div className="chat">
        <aside className="chat-side">
          <button className="btn primary chat-new" onClick={newChat}>
            + New chat
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
        </aside>

        <section className="chat-main">
          <div className="thread">
            {messages.length === 0 ? (
              <div className="muted pad">
                Ask about your stories — search, summarize an article, or manage
                favorites.
              </div>
            ) : (
              messages.map((m, i) => (
                <div key={i} className={`msg ${m.role}`}>
                  {m.tool_calls && m.tool_calls.length > 0 && (
                    <div className="tool-chips">
                      {m.tool_calls.map((t, j) => (
                        <span key={j} className="tool-chip">
                          {t.name}: {t.summary}
                        </span>
                      ))}
                    </div>
                  )}
                  <div className="msg-body">
                    {m.content || (m.role === "assistant" && sending ? "…" : "")}
                  </div>
                </div>
              ))
            )}
            <div ref={threadEnd} />
          </div>

          <form className="chat-input" onSubmit={send}>
            <input
              placeholder="Message briefbot…"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={sending}
            />
            <button className="btn primary" type="submit" disabled={sending || !input.trim()}>
              {sending ? "…" : "Send"}
            </button>
          </form>
        </section>
      </div>
    </div>
  );
}
