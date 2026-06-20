import { useCallback, useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import SearchIcon from "@mui/icons-material/Search";
import DownloadIcon from "@mui/icons-material/CloudDownloadOutlined";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import CheckIcon from "@mui/icons-material/Check";
import CloseIcon from "@mui/icons-material/Close";
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

  const load = useCallback(async () => {
    try {
      const [a, c, it] = await Promise.all([
        api.sources(slug, "active"),
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

  useEffect(() => {
    load();
  }, [load]);

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
      push(`Ingested ${stats.new} new item(s)`, "success");
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
    const n = candidates.length;
    try {
      await Promise.all(candidates.map((s) => api.approve(s.id)));
      push(`Approved ${n} source${n === 1 ? "" : "s"}`, "success");
      setCandidates([]);
      setActive(await api.sources(slug, "active"));
    } catch (e) {
      push(String(e), "error");
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
        <h2 className="section-title">Active sources ({active.length})</h2>
        {active.length === 0 ? (
          <p className="muted">
            None yet. Click <b>Discover sources</b>, approve a few, then{" "}
            <b>Collect now</b>.
          </p>
        ) : (
          <ul className="list">
            {active.map((s) => (
              <li key={s.id} className="list-row">
                <div className="src-info">
                  <div className="list-title">{s.name}</div>
                  <div className="muted small">{s.url}</div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="section">
        <h2 className="section-title">Recent items ({items.length})</h2>
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
          {items.length === 0 && <li className="muted">No items yet.</li>}
        </ul>
      </section>
    </div>
  );
}
