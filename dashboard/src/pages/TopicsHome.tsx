import { useEffect, useState } from "react";
import { api, type Topic } from "../api";
import { useToasts } from "../state/toasts";
import { LoadingBanner } from "../components/LoadingBanner";
import { ProvisionPipeline } from "../components/ProvisionPipeline";
import { DISCOVER_PHRASES } from "../lib/phrases";

export function TopicsHome() {
  const push = useToasts((s) => s.push);
  const [topics, setTopics] = useState<Topic[] | null>(null);
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [provisioning, setProvisioning] = useState<string | null>(null);
  const [stage, setStage] = useState<string | null>(null);

  const load = () =>
    api.topics().then(setTopics).catch((e) => push(String(e), "error"));

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
    if (!s || provisioning) return;
    try {
      const res = await api.createTopic({ slug: s, name: name.trim() || s });
      setSlug("");
      setName("");
      setProvisioning(res.slug);
      setStage(null);
      await api.provisionTopic(res.slug, (ev) => {
        if (ev.type === "stage") setStage(ev.stage as string);
        else if (ev.type === "error") push(String(ev.message), "error");
      });
      push(`"${res.slug}" is ready — subscribe below.`, "success");
    } catch (err) {
      // moderation 422 reason, rate-limit 429, etc. surface here
      push(String(err).replace(/^Error:\s*/, ""), "error");
    } finally {
      setProvisioning(null);
      setStage(null);
      load();
    }
  };

  return (
    <div className="page">
      <h1 className="page-title">Topics</h1>

      <form onSubmit={create} className="row-form card">
        <input
          placeholder="slug (e.g. hacking)"
          value={slug}
          onChange={(e) => setSlug(e.target.value)}
          disabled={!!provisioning}
        />
        <input
          placeholder="Display name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          disabled={!!provisioning}
        />
        <button className="btn primary" type="submit" disabled={!!provisioning}>
          {provisioning ? "Setting up…" : "Create topic"}
        </button>
      </form>

      {provisioning && (
        <div className="card">
          <div className="muted small">
            Setting up <b>{provisioning}</b> — finding sources and gathering stories…
          </div>
          <ProvisionPipeline stage={stage} />
          <LoadingBanner phrases={DISCOVER_PHRASES} />
        </div>
      )}

      {topics === null ? (
        <div className="muted pad">Loading…</div>
      ) : (
        <ul className="list">
          {topics.map((t) => (
            <li key={t.slug} className="list-row">
              <div>
                <div className="list-title">{t.name}</div>
                <div className="muted small">{t.slug}</div>
              </div>
              <button
                className={`btn ${t.subscribed ? "ghost" : "primary"}`}
                onClick={() => toggle(t)}
              >
                {t.subscribed ? "Subscribed ✓" : "Subscribe"}
              </button>
            </li>
          ))}
          {topics.length === 0 && (
            <li className="muted pad">No topics yet — create one above.</li>
          )}
        </ul>
      )}
    </div>
  );
}
