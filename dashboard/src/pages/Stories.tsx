import { useCallback, useEffect, useState } from "react";
import { api, type Story } from "../api";
import { useToasts } from "../state/toasts";
import { timeAgo } from "../lib/format";

type Order = "desc" | "asc";

export function Stories() {
  const push = useToasts((s) => s.push);
  const [sources, setSources] = useState<string[]>([]);
  const [stories, setStories] = useState<Story[] | null>(null);
  const [search, setSearch] = useState("");
  const [source, setSource] = useState("");
  const [order, setOrder] = useState<Order>("desc");

  const load = useCallback(async () => {
    setStories(null);
    try {
      const items = await api.queryStories({
        search: search.trim() || undefined,
        source: source || undefined,
        order,
        limit: 50,
      });
      setStories(items);
    } catch (e) {
      push(String(e), "error");
      setStories([]);
    }
  }, [search, source, order, push]);

  useEffect(() => {
    api.storySources().then(setSources).catch((e) => push(String(e), "error"));
  }, [push]);

  // Source/sort changes reload immediately; free-text search applies on submit.
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source, order]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    load();
  };

  const vote = async (s: Story, v: number) => {
    const next = s.feedback_vote === v ? 0 : v; // click the active vote to clear it
    try {
      await api.setFeedback(s.item_id, next);
      setStories((prev) =>
        prev
          ? prev.map((x) =>
              x.item_id === s.item_id ? { ...x, feedback_vote: next } : x,
            )
          : prev,
      );
    } catch (e) {
      push(String(e), "error");
    }
  };

  return (
    <div className="page">
      <h1 className="page-title">Stories</h1>

      <form className="row-form card" onSubmit={submit}>
        <input
          placeholder="Search title, summary, source…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select value={source} onChange={(e) => setSource(e.target.value)}>
          <option value="">All sources</option>
          {sources.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="btn"
          onClick={() => setOrder((o) => (o === "desc" ? "asc" : "desc"))}
        >
          {order === "desc" ? "Newest first" : "Oldest first"}
        </button>
        <button className="btn primary" type="submit">
          Search
        </button>
      </form>

      {stories === null ? (
        <div className="muted pad">Loading stories…</div>
      ) : stories.length === 0 ? (
        <div className="empty">
          <h2>No stories</h2>
          <p className="muted">
            Subscribe to topics and collect their sources to see stories here.
          </p>
        </div>
      ) : (
        <ul className="feed">
          {stories.map((s) => (
            <li key={s.item_id} className="feed-item">
              <a
                href={s.url ?? "#"}
                target="_blank"
                rel="noreferrer"
                className="feed-title"
              >
                {s.title}
              </a>
              {s.summary && <p className="muted small story-summary">{s.summary}</p>}
              <div className="feed-meta">
                <span className="chip">{s.source_name}</span>
                <span className="muted">
                  {timeAgo(s.published_at ?? s.fetched_at)}
                </span>
                <span className="vote">
                  <button
                    className={`vote-btn${s.feedback_vote === 1 ? " on" : ""}`}
                    onClick={() => vote(s, 1)}
                    aria-label="Thumbs up"
                    title="Thumbs up"
                  >
                    ▲
                  </button>
                  <button
                    className={`vote-btn${s.feedback_vote === -1 ? " on" : ""}`}
                    onClick={() => vote(s, -1)}
                    aria-label="Thumbs down"
                    title="Thumbs down"
                  >
                    ▼
                  </button>
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
