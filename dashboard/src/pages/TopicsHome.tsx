import { useEffect, useRef, useState } from "react";
import AddIcon from "@mui/icons-material/Add";
import TopicIcon from "@mui/icons-material/TagOutlined";
import { api, type Topic } from "../api";
import { useToasts } from "../state/toasts";
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
  const [provisioning, setProvisioning] = useState<string | null>(null);
  const [stage, setStage] = useState<string | null>(null);
  const [failedStage, setFailedStage] = useState<string | null>(null);
  const provisionAbort = useRef<AbortController | null>(null);

  const load = () =>
    api.topics().then(setTopics).catch((e) => push(String(e), "error"));

  useEffect(() => {
    load();
    // Abort an in-flight provision stream if the user leaves mid-provision.
    return () => provisionAbort.current?.abort();
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
    const display = name.trim();
    const s = slugify(display);
    if (!s || provisioning) return;
    try {
      const res = await api.createTopic({
        slug: s,
        name: display,
        description: description.trim() || undefined,
      });
      setName("");
      setDescription("");
      setProvisioning(res.slug);
      setStage(null);
      setFailedStage(null);
      let lastStage: string | null = null;
      let didFail = false;
      provisionAbort.current = new AbortController();
      await api.provisionTopic(res.slug, (ev) => {
        if (ev.type === "stage") {
          lastStage = ev.stage as string;
          setStage(lastStage);
        } else if (ev.type === "error") {
          didFail = true;
          push(String(ev.message), "error");
        }
      }, provisionAbort.current.signal);
      if (didFail) {
        setFailedStage(lastStage ?? "discovering");
      } else {
        // Auto-subscribe to the freshly provisioned topic; user can unsubscribe below.
        try {
          await api.subscribe(res.slug);
          push(`"${res.slug}" is ready — you're subscribed.`, "success");
        } catch {
          // The topic provisioned fine; only the subscribe failed — say so plainly.
          push(`"${res.slug}" is ready — but subscribing failed; try the ☆ below.`, "info");
        }
      }
    } catch (err) {
      if (provisionAbort.current?.signal.aborted) return; // unmounted — ignore
      // moderation 422 reason, rate-limit 429, etc. surface here
      setFailedStage((s) => s ?? stage ?? "discovering");
      push(String(err).replace(/^Error:\s*/, ""), "error");
    } finally {
      if (!provisionAbort.current?.signal.aborted) {
        setProvisioning(null);
        setStage(null);
        load();
      }
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
          disabled={!!provisioning}
        />
        <input
          placeholder="Describe your topic"
          value={description}
          maxLength={200}
          onChange={(e) => setDescription(e.target.value)}
          disabled={!!provisioning}
        />
        <button
          className="btn primary icon-btn-text"
          type="submit"
          disabled={!!provisioning}
        >
          <AddIcon fontSize="small" />
          {provisioning ? "Setting up…" : "Create topic"}
        </button>
      </form>

      {provisioning ? (
        <div className="card">
          <div className="muted small">
            Setting up <b>{provisioning}</b> — finding sources and gathering stories…
          </div>
          <ProvisionPipeline stage={stage} />
          <LoadingBanner phrases={DISCOVER_PHRASES} />
        </div>
      ) : (
        failedStage && (
          <div className="card">
            <div className="muted small">Setup failed — see the error above.</div>
            <ProvisionPipeline stage={failedStage} failed />
          </div>
        )
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
