import { useEffect, useState } from "react";
import { api, type Brief, type Item, type TopicTab } from "../api";
import { useToasts } from "../state/toasts";
import { timeAgo } from "../lib/format";

const TODAY = "__today__";

function paragraphs(text: string): string[] {
  return text
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter(Boolean);
}

export function Headlines() {
  const push = useToasts((s) => s.push);
  const [tabs, setTabs] = useState<TopicTab[]>([]);
  const [briefs, setBriefs] = useState<Brief[] | null>(null);
  const [active, setActive] = useState<string>(TODAY);
  const [items, setItems] = useState<Item[] | null>(null);

  useEffect(() => {
    api
      .briefs()
      .then((d) => {
        setBriefs(d.briefs);
        setTabs(d.topics);
      })
      .catch((e) => {
        push(String(e), "error");
        setBriefs([]);
      });
  }, [push]);

  // A topic tab shows that topic's stories (newest first).
  useEffect(() => {
    if (active === TODAY) return;
    setItems(null);
    api
      .topicItems(active, 50)
      .then(setItems)
      .catch((e) => {
        push(String(e), "error");
        setItems([]);
      });
  }, [active, push]);

  return (
    <div className="page">
      <div className="tabs">
        <button
          className={`tab${active === TODAY ? " active" : ""}`}
          onClick={() => setActive(TODAY)}
        >
          Today
        </button>
        {tabs.map((t) => (
          <button
            key={t.slug}
            className={`tab${active === t.slug ? " active" : ""}`}
            onClick={() => setActive(t.slug)}
          >
            {t.name}
          </button>
        ))}
      </div>

      {active === TODAY ? (
        briefs === null ? (
          <div className="muted pad">Loading brief…</div>
        ) : briefs.length === 0 ? (
          <div className="empty">
            <h2>No brief yet</h2>
            <p className="muted">
              Subscribe to a topic, then generate its brief (Admin →{" "}
              <b>Generate brief</b>, or <code>bbv2 brief</code>).
            </p>
          </div>
        ) : (
          briefs.map((b) => <BriefCard key={b.topic_slug} brief={b} />)
        )
      ) : (
        <ItemList items={items} />
      )}
    </div>
  );
}

function BriefCard({ brief }: { brief: Brief }) {
  const push = useToasts((s) => s.push);
  const save = async (title: string, url: string | null) => {
    if (!url) return;
    try {
      await api.addFavorite({ title, url });
      push("Saved to favorites", "success");
    } catch (e) {
      push(String(e), "error");
    }
  };
  return (
    <section className="brief">
      <div className="brief-head">
        <span className="chip">{brief.topic_name}</span>
        <span className="muted small">{brief.date}</span>
      </div>
      <h1 className="brief-title">{brief.title}</h1>
      <div className="brief-summary">
        {paragraphs(brief.summary).map((p, i) => (
          <p key={i}>{p}</p>
        ))}
      </div>

      {brief.trending.length > 0 && (
        <div className="brief-section">
          <h2 className="section-title">Trending</h2>
          <ul className="list">
            {brief.trending.map((t, i) => (
              <li key={i} className="list-row">
                <div className="src-info">
                  <div className="list-title">{t.label}</div>
                  {t.representative_title && (
                    <a
                      className="muted small"
                      href={t.representative_url ?? "#"}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {t.representative_title}
                    </a>
                  )}
                </div>
                <span className="chip">
                  {t.item_count} {t.item_count === 1 ? "story" : "stories"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {brief.sources.length > 0 && (
        <div className="brief-section">
          <h2 className="section-title">Sources</h2>
          <ul className="feed">
            {brief.sources.map((s, i) => (
              <li key={i} className="feed-item">
                <a
                  className="feed-title"
                  href={s.url ?? "#"}
                  target="_blank"
                  rel="noreferrer"
                >
                  {s.title}
                </a>
                <div className="feed-meta">
                  <span className="chip">{s.source_name}</span>
                  <span className="vote">
                    <button
                      className="vote-btn"
                      onClick={() => save(s.title, s.url)}
                      disabled={!s.url}
                      aria-label="Save to favorites"
                      title="Save to favorites"
                    >
                      ☆
                    </button>
                  </span>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function ItemList({ items }: { items: Item[] | null }) {
  if (items === null) return <div className="muted pad">Loading…</div>;
  if (items.length === 0)
    return (
      <div className="empty">
        <h2>No stories yet</h2>
        <p className="muted">Nothing collected for this topic yet.</p>
      </div>
    );
  return (
    <ul className="feed">
      {items.map((it) => (
        <li key={it.item_id} className="feed-item">
          <a
            href={it.url ?? "#"}
            target="_blank"
            rel="noreferrer"
            className="feed-title"
          >
            {it.title}
          </a>
          <div className="feed-meta">
            <span className="chip">{it.source_name}</span>
            <span className="muted">{timeAgo(it.published_at ?? it.fetched_at)}</span>
          </div>
        </li>
      ))}
    </ul>
  );
}
