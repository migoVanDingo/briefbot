import { useEffect, useState } from "react";
import { api, type Item } from "../api";
import { useToasts } from "../state/toasts";
import { timeAgo } from "../lib/format";

export function Headlines() {
  const push = useToasts((s) => s.push);
  const [items, setItems] = useState<Item[] | null>(null);

  useEffect(() => {
    let on = true;
    api
      .headlines(60)
      .then((d) => on && setItems(d))
      .catch((e) => on && (push(String(e), "error"), setItems([])));
    return () => {
      on = false;
    };
  }, [push]);

  if (items === null) return <div className="muted pad">Loading headlines…</div>;
  if (items.length === 0)
    return (
      <div className="empty">
        <h2>No headlines yet</h2>
        <p className="muted">
          Subscribe to topics (and approve some sources) to see items here.
        </p>
      </div>
    );

  return (
    <div className="page">
      <h1 className="page-title">Headlines</h1>
      <ul className="feed">
        {items.map((it) => (
          <li key={it.item_id} className="feed-item">
            <a href={it.url ?? "#"} target="_blank" rel="noreferrer" className="feed-title">
              {it.title}
            </a>
            <div className="feed-meta">
              <span className="chip">{it.source_name}</span>
              <span className="muted">{timeAgo(it.published_at ?? it.fetched_at)}</span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
