import { useCallback, useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import SearchIcon from "@mui/icons-material/Search";
import DownloadIcon from "@mui/icons-material/CloudDownloadOutlined";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import CheckIcon from "@mui/icons-material/Check";
import CloseIcon from "@mui/icons-material/Close";
import DeleteIcon from "@mui/icons-material/DeleteOutlined";
import { api, type Source, type Item } from "../../api";
import { useToasts } from "../../state/toasts";
import { timeAgo } from "../../lib/format";
import { LoadingBanner } from "../../components/LoadingBanner";
import { DISCOVER_PHRASES, COLLECT_PHRASES } from "../../lib/phrases";

export function TopicDetail() {
  const { slug = "" } = useParams();
  const push = useToasts((s) => s.push);

  const [active, setActive] = useState<Source[]>([]);
  const [candidates, setCandidates] = useState<Source[]>([]);
  const [items, setItems] = useState<Item[]>([]);
  const [discovering, setDiscovering] = useState(false);
  const [collecting, setCollecting] = useState(false);
  const [briefing, setBriefing] = useState(false);
  // Click a source card to filter Recent items to that source.
  const [selected, setSelected] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const [a, c, it] = await Promise.all([
        api.sources(slug, "managed"), // active + disabled (paused)
        api.sources(slug, "candidate"),
        api.topicItems(slug, 30),
      ]);
      setActive(a);
      setCandidates(c);
      setItems(it);
    } catch (e) {
      push(String(e), "error");
    }
  }, [slug, push]);

  const saveSourceCadence = async (id: number, value: string) => {
    try {
      await api.setSourceCadence(id, value ? Number(value) : null);
      push("Source cadence saved", "success");
    } catch (e) {
      push(String(e), "error");
    }
  };

  const toggleEnabled = async (s: Source) => {
    try {
      if (s.status === "disabled") {
        await api.enableSource(s.id);
        push(`Enabled ${s.name}`, "success");
      } else {
        await api.disableSource(s.id);
        push(`Disabled ${s.name}`, "info");
      }
      load();
    } catch (e) {
      push(String(e), "error");
    }
  };

  const removeSource = async (s: Source) => {
    if (!window.confirm(`Delete source "${s.name}"? Collected stories are kept.`)) return;
    try {
      await api.deleteSource(s.id);
      if (selected === s.id) setSelected(null);
      push(`Deleted ${s.name}`, "info");
      load();
    } catch (e) {
      push(String(e), "error");
    }
  };

  useEffect(() => {
    load();
  }, [load]);

  const selectedSource = active.find((s) => s.id === selected) ?? null;
  const shownItems = selectedSource
    ? items.filter((it) => it.source_name === selectedSource.name)
    : items;

  const discover = async () => {
    setDiscovering(true);
    try {
      const stats = await api.discover(slug);
      push(`Found ${stats.candidates} candidate source(s)`, "success");
      setCandidates(await api.sources(slug, "candidate"));
    } catch (e) {
      push(String(e), "error");
    } finally {
      setDiscovering(false);
    }
  };

  const collect = async () => {
    setCollecting(true);
    try {
      const stats = await api.collect(slug);
      const dropped = stats.dropped ? `, dropped ${stats.dropped} off-topic` : "";
      push(`Ingested ${stats.new} new item(s)${dropped}`, "success");
      setItems(await api.topicItems(slug, 30));
    } catch (e) {
      push(String(e), "error");
    } finally {
      setCollecting(false);
    }
  };

  const makeBrief = async () => {
    setBriefing(true);
    try {
      const r = await api.generateBrief(slug);
      push(`Brief ready: ${r.title}`, "success");
    } catch (e) {
      push(String(e), "error");
    } finally {
      setBriefing(false);
    }
  };

  const approve = async (s: Source) => {
    try {
      await api.approve(s.id);
      push(`Approved ${s.name}`, "success");
      setCandidates((c) => c.filter((x) => x.id !== s.id));
      setActive(await api.sources(slug, "active"));
    } catch (e) {
      push(String(e), "error");
    }
  };

  const reject = async (s: Source) => {
    try {
      await api.reject(s.id);
      push(`Rejected ${s.name}`, "info");
      setCandidates((c) => c.filter((x) => x.id !== s.id));
    } catch (e) {
      push(String(e), "error");
    }
  };

  const approveAll = async () => {
    try {
      // One transactional endpoint instead of N parallel POSTs (which raced and
      // surfaced "failed to fetch", losing partial progress on error).
      const { approved } = await api.approveAll(slug);
      push(`Approved ${approved} source${approved === 1 ? "" : "s"}`, "success");
      setCandidates([]);
      setActive(await api.sources(slug, "active"));
    } catch (e) {
      // Re-sync both lists so any partial server-side progress is reflected.
      push(String(e), "error");
      setCandidates(await api.sources(slug, "candidate").catch(() => candidates));
      setActive(await api.sources(slug, "active").catch(() => []));
    }
  };

  return (
    <div className="page">
      <Link to="/admin/topics" className="back-link">
        ← Topics (admin)
      </Link>
      <div className="detail-head">
        <h1 className="page-title">{slug}</h1>
        <div className="detail-actions">
          <button
            className="btn icon-btn-text"
            onClick={discover}
            disabled={discovering}
          >
            <SearchIcon fontSize="small" />
            {discovering ? "Discovering…" : "Discover sources"}
          </button>
          <button
            className="btn primary icon-btn-text"
            onClick={collect}
            disabled={collecting}
          >
            <DownloadIcon fontSize="small" />
            {collecting ? "Collecting…" : "Collect now"}
          </button>
          <button
            className="btn icon-btn-text"
            onClick={makeBrief}
            disabled={briefing}
          >
            <AutoAwesomeIcon fontSize="small" />
            {briefing ? "Briefing…" : "Generate brief"}
          </button>
        </div>
      </div>

      {discovering && <LoadingBanner phrases={DISCOVER_PHRASES} />}
      {collecting && <LoadingBanner phrases={COLLECT_PHRASES} />}

      <section className="section">
        <h2 className="section-title">Cadence</h2>
        <p className="muted small">
          This topic's discovery + collection schedule and ingest caps live in{" "}
          <Link to="/admin/scheduling">Admin → Scheduling</Link>. Per-source
          collection overrides (below) still win over the topic schedule.
        </p>
      </section>

      {candidates.length > 0 && (
        <section className="section">
          <div className="section-head">
            <h2 className="section-title">
              Candidate sources — approve the good ones
            </h2>
            <button className="btn primary" onClick={approveAll}>
              Approve all ({candidates.length})
            </button>
          </div>
          <ul className="list">
            {candidates.map((s) => (
              <li key={s.id} className="list-row">
                <div className="src-info">
                  <div className="list-title">{s.name}</div>
                  <div className="muted small">{s.url}</div>
                </div>
                <div className="src-actions">
                  <button
                    className="btn primary icon-btn-text"
                    onClick={() => approve(s)}
                  >
                    <CheckIcon fontSize="small" />
                    Approve
                  </button>
                  <button
                    className="btn ghost icon-btn-text"
                    onClick={() => reject(s)}
                  >
                    <CloseIcon fontSize="small" />
                    Reject
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="section">
        <h2 className="section-title">Sources ({active.length})</h2>
        {active.length === 0 ? (
          <p className="muted">
            None yet. Click <b>Discover sources</b>, approve a few, then{" "}
            <b>Collect now</b>.
          </p>
        ) : (
          <>
            <p className="muted small">Click a source to filter the items below.</p>
            <ul className="list">
              {active.map((s) => (
                <li
                  key={s.id}
                  className={`list-row src-card${selected === s.id ? " selected" : ""}${s.status === "disabled" ? " disabled" : ""}`}
                  onClick={() => setSelected(selected === s.id ? null : s.id)}
                >
                  <div className="src-info">
                    <div className="list-title">
                      {s.name}
                      {s.status === "disabled" && <span className="chip danger">disabled</span>}
                    </div>
                    <div className="muted small">{s.url}</div>
                  </div>
                  <label
                    className="cadence-input src-cadence"
                    title="Collect every (min); blank = topic default"
                    onClick={(e) => e.stopPropagation()}
                  >
                    every
                    <input
                      type="number"
                      min={0}
                      defaultValue={s.collect_interval_min ?? ""}
                      placeholder="default"
                      onBlur={(e) => saveSourceCadence(s.id, e.target.value)}
                    />
                    min
                  </label>
                  <div className="src-actions" onClick={(e) => e.stopPropagation()}>
                    <button className="btn ghost" onClick={() => toggleEnabled(s)}>
                      {s.status === "disabled" ? "Enable" : "Disable"}
                    </button>
                    <button
                      className="btn ghost icon-btn-text danger"
                      onClick={() => removeSource(s)}
                      title="Delete source"
                    >
                      <DeleteIcon fontSize="small" />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      <section className="section">
        <div className="section-head">
          <h2 className="section-title">
            Recent items ({shownItems.length})
            {selectedSource && (
              <span className="muted small"> · {selectedSource.name}</span>
            )}
          </h2>
          {selectedSource && (
            <button className="btn ghost" onClick={() => setSelected(null)}>
              Show all
            </button>
          )}
        </div>
        <ul className="feed">
          {shownItems.map((it) => (
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
          {shownItems.length === 0 && (
            <li className="muted">
              {selectedSource ? "No recent items from this source." : "No items yet."}
            </li>
          )}
        </ul>
      </section>
    </div>
  );
}
