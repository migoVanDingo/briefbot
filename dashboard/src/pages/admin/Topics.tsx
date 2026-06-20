import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Topic } from "../../api";
import { useToasts } from "../../state/toasts";

export function Topics() {
  const push = useToasts((s) => s.push);
  const [topics, setTopics] = useState<Topic[] | null>(null);
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");

  const load = () =>
    api
      .topics()
      .then(setTopics)
      .catch((e) => push(String(e), "error"));

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toggle = async (t: Topic) => {
    try {
      if (t.subscribed) {
        await api.unsubscribe(t.slug);
        push(`Unsubscribed from ${t.name}`, "info");
      } else {
        await api.subscribe(t.slug);
        push(`Subscribed to ${t.name}`, "success");
      }
      setTopics((prev) =>
        prev
          ? prev.map((x) =>
              x.slug === t.slug ? { ...x, subscribed: !x.subscribed } : x,
            )
          : prev,
      );
    } catch (e) {
      push(String(e), "error");
    }
  };

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    const s = slug.trim().toLowerCase();
    if (!s) return;
    try {
      await api.createTopic({ slug: s, name: name.trim() || s });
      push(`Created topic ${s}`, "success");
      setSlug("");
      setName("");
      load();
    } catch (err) {
      push(String(err), "error");
    }
  };

  return (
    <div className="page">
      <h1 className="page-title">Topics (admin)</h1>

      <form onSubmit={create} className="row-form card">
        <input
          placeholder="slug (e.g. crypto)"
          value={slug}
          onChange={(e) => setSlug(e.target.value)}
        />
        <input
          placeholder="Display name"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <button className="btn primary" type="submit">
          Add topic
        </button>
      </form>

      {topics === null ? (
        <div className="muted pad">Loading…</div>
      ) : (
        <ul className="list">
          {topics.map((t) => (
            <li key={t.slug} className="list-row">
              <div>
                <Link to={`/admin/topics/${t.slug}`} className="list-title link">
                  {t.name}
                </Link>
                <div className="muted small">{t.slug}</div>
              </div>
              <div className="src-actions">
                <Link to={`/admin/topics/${t.slug}`} className="btn ghost">
                  Sources
                </Link>
                <button
                  className={`btn ${t.subscribed ? "ghost" : "primary"}`}
                  onClick={() => toggle(t)}
                >
                  {t.subscribed ? "Subscribed ✓" : "Subscribe"}
                </button>
              </div>
            </li>
          ))}
          {topics.length === 0 && (
            <li className="muted pad">No topics yet — add one above.</li>
          )}
        </ul>
      )}
    </div>
  );
}
