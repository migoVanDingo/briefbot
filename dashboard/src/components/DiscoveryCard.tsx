import { useState } from "react";
import SearchIcon from "@mui/icons-material/Search";
import AddIcon from "@mui/icons-material/Add";
import { api, type DiscoveryRun, type PlacementDecision } from "../api";
import { useToasts } from "../state/toasts";
import { LoadingBanner } from "./LoadingBanner";
import { DISCOVER_PHRASES } from "../lib/phrases";

// The in-chat results card for an on-demand source search (0030). While running it
// shows a spinner + rotating phrases; when done, a compact list of the discovered
// sources (named by site) with a couple of their latest headlines, a collapsible
// "also on the web", and an "Add these sources" button that routes them via the
// embedding index.
const MAX_HEADLINES = 2;
const MAX_WEB = 5;

export function DiscoveryCard({
  run,
  onCommitted,
}: {
  run: DiscoveryRun;
  onCommitted?: () => void;
}) {
  const push = useToasts((s) => s.push);
  const [committing, setCommitting] = useState(false);
  const [decision, setDecision] = useState<PlacementDecision | null>(null);
  const [dismissed, setDismissed] = useState(false);

  if (dismissed) return null;

  const plural = (k: number) => (k === 1 ? "" : "s");

  const add = async () => {
    setCommitting(true);
    try {
      const d = await api.commitDiscovery(run.id);
      setDecision(d);
      const where = d.topics.map((t) => t.name).join(", ");
      push(
        d.created_new
          ? `Created “${where}” and added ${d.sources_added} source${plural(d.sources_added)}`
          : `Added ${d.sources_added} source${plural(d.sources_added)} to ${where}`,
        "success",
      );
      onCommitted?.();
    } catch (e) {
      push(String(e), "error");
    } finally {
      setCommitting(false);
    }
  };

  const candidates = run.candidates ?? [];
  const web = run.web_results ?? [];

  return (
    <div className="discovery-card">
      <div className="discovery-head">
        <SearchIcon fontSize="small" />
        <span className="discovery-query">“{run.query}”</span>
      </div>

      {run.status === "running" ? (
        <LoadingBanner phrases={DISCOVER_PHRASES} />
      ) : run.failed ? (
        <div className="muted small">Search failed{run.error ? `: ${run.error}` : ""}.</div>
      ) : decision ? (
        <div className="discovery-done">
          <div>
            ✓{" "}
            {decision.created_new ? (
              <>
                Created <b>{decision.topics[0]?.name}</b> and added {decision.sources_added}{" "}
                source{plural(decision.sources_added)}.
              </>
            ) : (
              <>
                Added {decision.sources_added} source{plural(decision.sources_added)} to{" "}
                <b>{decision.topics.map((t) => t.name).join(", ")}</b>.
              </>
            )}
          </div>
          <div className="muted small discovery-followup">
            They'll appear in your morning brief starting tomorrow — explore them now on
            the Stories page or ask me to search them.
          </div>
        </div>
      ) : candidates.length === 0 && web.length === 0 ? (
        <div className="muted small">No sources found — try rephrasing.</div>
      ) : (
        <>
          {candidates.length > 0 && (
            <div className="discovery-sources">
              <div className="discovery-subhead">Sources ({candidates.length})</div>
              <ul>
                {candidates.map((c) => {
                  // Guard against older/partial runs that predate `sample_articles`.
                  const arts = c.sample_articles ?? [];
                  return (
                    <li key={c.url}>
                      <a
                        className="discovery-source-name"
                        href={c.url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {c.name}
                      </a>
                      {arts.length > 0 && (
                        <div className="discovery-headlines">
                          {arts.slice(0, MAX_HEADLINES).map((a) => a.title).join(" · ")}
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          )}

          {web.length > 0 && (
            <details className="discovery-web">
              <summary className="discovery-subhead">Also on the web ({web.length})</summary>
              <ul>
                {web.slice(0, MAX_WEB).map((w) => (
                  <li key={w.url}>
                    <a href={w.url} target="_blank" rel="noreferrer">
                      {w.title || w.url}
                    </a>
                  </li>
                ))}
              </ul>
            </details>
          )}

          {!run.committed && (
            <div className="discovery-actions">
              <button
                className="btn primary icon-btn-text"
                onClick={add}
                disabled={committing}
              >
                <AddIcon fontSize="small" /> {committing ? "Adding…" : "Add these sources"}
              </button>
              <button
                className="btn ghost"
                onClick={() => setDismissed(true)}
                disabled={committing}
              >
                Dismiss
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
