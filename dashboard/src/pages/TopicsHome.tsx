import { useEffect, useRef, useState } from "react";
import AddIcon from "@mui/icons-material/Add";
import TopicIcon from "@mui/icons-material/TagOutlined";
import { api, type Topic } from "../api";
import { useToasts } from "../state/toasts";
import { useProvisioning } from "../lib/useProvisioning";
import { LoadingBanner } from "../components/LoadingBanner";
import { ProvisionPipeline } from "../components/ProvisionPipeline";
import { PageTour } from "../components/PageTour";
import { DISCOVER_PHRASES } from "../lib/phrases";

function slugify(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
}

export function TopicsHome() {
  const push = useToasts((s) => s.push);
  const [topics, setTopics] = useState<Topic[] | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);
  // Active provisioning pipelines (any surface), polled so they persist + appear
  // here even if started from chat (0023).
  const { runs, refresh: refreshRuns } = useProvisioning();
  // Run ids whose terminal state we've already reacted to (subscribe / toast).
  const handled = useRef<Set<string>>(new Set());

  const load = () =>
    api.topics().then(setTopics).catch((e) => push(String(e), "error"));

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // When a topics-initiated run finishes, auto-subscribe + refresh the list.
  useEffect(() => {
    for (const r of runs) {
      if (r.surface !== "topics" || r.status === "running") continue;
      if (handled.current.has(r.id)) continue;
      handled.current.add(r.id);
      if (r.status === "done") {
        api
          .subscribe(r.slug)
          .then(() => push(`"${r.name}" is ready — you're subscribed.`, "success"))
          .catch(() =>
            push(`"${r.name}" is ready — subscribe failed; use the button below.`, "info"),
          )
          .finally(load);
      } else {
        push(`"${r.name}": ${r.error || "setup failed"}`, "error");
        load();
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runs]);

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
    const display = name.trim();
    const s = slugify(display);
    if (!s || creating) return;
    setCreating(true);
    try {
      await api.createTopic({
        slug: s,
        name: display,
        description: description.trim() || undefined,
      });
      setName("");
      setDescription("");
      await api.provisionTopic(s); // starts the background run
      refreshRuns(); // show the pipeline card immediately
    } catch (err) {
      // moderation 422 reason, rate-limit 429, etc. surface here
      push(String(err).replace(/^Error:\s*/, ""), "error");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="page">
      <h1 className="page-title">
        <TopicIcon className="title-ico" /> Topics
        <PageTour page="topics" ready={topics !== null} />
      </h1>

      <form onSubmit={create} className="row-form card" data-tour="topics-create">
        <input
          placeholder="Display name (e.g. Crypto)"
          value={name}
          maxLength={80}
          onChange={(e) => setName(e.target.value)}
          disabled={creating}
        />
        <input
          placeholder="Describe your topic"
          value={description}
          maxLength={200}
          onChange={(e) => setDescription(e.target.value)}
          disabled={creating}
        />
        <button className="btn primary icon-btn-text" type="submit" disabled={creating}>
          <AddIcon fontSize="small" />
          {creating ? "Starting…" : "Create topic"}
        </button>
      </form>

      {/* One card per RUNNING pipeline. Finished ones disappear (a done card here
          is just wasted space — chat keeps the history since it's conversational). */}
      {runs.filter((r) => r.status === "running").length > 0 && (
        <div className="provision-cards">
          {runs
            .filter((r) => r.status === "running")
            .map((r) => (
              <div key={r.id} className="card provision-card">
                <div className="muted small">
                  Setting up <b>{r.name}</b> — finding sources and gathering stories…
                </div>
                <ProvisionPipeline stage={r.stage} failed={r.failed} />
                <LoadingBanner phrases={DISCOVER_PHRASES} />
              </div>
            ))}
        </div>
      )}

      {topics === null ? (
        <div className="muted pad">Loading…</div>
      ) : (
        <ul className="list" data-tour="topics-list">
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
