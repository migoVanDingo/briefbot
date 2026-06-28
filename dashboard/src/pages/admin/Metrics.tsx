import { useEffect, useState } from "react";
import InsightsIcon from "@mui/icons-material/InsightsOutlined";
import TrendingUpIcon from "@mui/icons-material/TrendingUp";
import TrendingDownIcon from "@mui/icons-material/TrendingDown";
import CloseIcon from "@mui/icons-material/Close";
import { api, type LlmMetrics, type UserDetail, type UserMetrics } from "../../api";
import { AdminNav } from "../../components/AdminNav";
import { useToasts } from "../../state/toasts";
import { timeAgo } from "../../lib/format";

const RANGES = ["7d", "30d", "90d"];
const usd = (n: number) => `$${n.toFixed(n < 1 ? 4 : 2)}`;
const num = (n: number) => n.toLocaleString();

function Trend({ pct }: { pct: number | null }) {
  if (pct == null) return <span className="muted small">no prior data</span>;
  const up = pct >= 0;
  return (
    <span className={`trend ${up ? "up" : "down"}`}>
      {up ? <TrendingUpIcon fontSize="small" /> : <TrendingDownIcon fontSize="small" />}
      {Math.abs(pct)}% vs prior period
    </span>
  );
}

export function Metrics() {
  const push = useToasts((s) => s.push);
  const [range, setRange] = useState("30d");
  const [llm, setLlm] = useState<LlmMetrics | null>(null);
  const [users, setUsers] = useState<UserMetrics | null>(null);
  const [selected, setSelected] = useState<number | null>(null);

  useEffect(() => {
    api.adminLlmMetrics(range).then(setLlm).catch((e) => push(String(e), "error"));
  }, [range, push]);
  useEffect(() => {
    api.adminUserMetrics().then(setUsers).catch((e) => push(String(e), "error"));
  }, [push]);

  return (
    <div className="page">
      <h1 className="page-title">
        <InsightsIcon className="title-ico" /> Metrics
      </h1>
      <AdminNav />

      {/* ---- LLM cost ---- */}
      <div className="metrics-head">
        <h2 className="section-title">LLM cost (estimated)</h2>
        <div className="range-pick">
          {RANGES.map((r) => (
            <button
              key={r}
              className={`chip-btn${range === r ? " active" : ""}`}
              onClick={() => setRange(r)}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      {!llm ? (
        <div className="muted pad">Loading…</div>
      ) : (
        <>
          <div className="metric-cards">
            <div className="metric-card card">
              <div className="metric-label">Est. spend ({llm.range})</div>
              <div className="metric-big">{usd(llm.overall.cost)}</div>
              <Trend pct={llm.trend.delta_pct} />
            </div>
            <div className="metric-card card">
              <div className="metric-label">Tokens</div>
              <div className="metric-big">{num(llm.overall.input + llm.overall.output)}</div>
              <span className="muted small">
                {num(llm.overall.input)} in · {num(llm.overall.output)} out
              </span>
            </div>
            <div className="metric-card card">
              <div className="metric-label">LLM calls</div>
              <div className="metric-big">{num(llm.overall.calls)}</div>
            </div>
            <div className="metric-card card">
              <div className="metric-label">Header images</div>
              <div className="metric-big">{num(llm.images.count)}</div>
              <span className="muted small">
                {usd(llm.images.cost)} · {usd(llm.images.unit_price)}/img
              </span>
            </div>
          </div>

          <p className="muted small">
            Estimated from token volume × list price (images priced per image) — a cost
            trend, not an invoice.
          </p>

          {/* Where the tokens go, and for what. */}
          <div className="metric-table card wide">
            <h3>By purpose</h3>
            <table>
              <thead>
                <tr><th>What</th><th>Calls</th><th>Tokens</th><th>Est. cost</th></tr>
              </thead>
              <tbody>
                {llm.by_purpose.map((p) => (
                  <tr key={p.purpose}>
                    <td>
                      <span className="purpose-label">{p.label}</span>
                      {p.description && (
                        <span className="muted small block">{p.description}</span>
                      )}
                    </td>
                    <td>{num(p.calls)}</td>
                    <td>{num(p.input + p.output)}</td>
                    <td>{usd(p.cost)}</td>
                  </tr>
                ))}
                {llm.by_purpose.length === 0 && (
                  <tr><td colSpan={4} className="muted">No usage in range.</td></tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="metric-tables">
            <div className="metric-table card">
              <h3>By topic</h3>
              <table>
                <thead>
                  <tr><th>Topic</th><th>Tokens</th><th>Est. cost</th></tr>
                </thead>
                <tbody>
                  {llm.by_topic.map((t) => (
                    <tr key={t.slug ?? t.name}>
                      <td>
                        {t.name}
                        {t.kind === "background" && (
                          <span className="chip" title="Chat, moderation, and system work not tied to one topic">
                            shared
                          </span>
                        )}
                      </td>
                      <td>{num(t.input + t.output)}</td>
                      <td>{usd(t.cost)}</td>
                    </tr>
                  ))}
                  {llm.by_topic.length === 0 && (
                    <tr><td colSpan={3} className="muted">No usage in range.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
            <div className="metric-table card">
              <h3>By model</h3>
              <table>
                <thead>
                  <tr><th>Model</th><th>Calls</th><th>Tokens</th><th>Est. cost</th></tr>
                </thead>
                <tbody>
                  {llm.by_model.map((m) => (
                    <tr key={m.model}>
                      <td>{m.model}</td>
                      <td>{num(m.calls)}</td>
                      <td>{num(m.input + m.output)}</td>
                      <td>{usd(m.cost)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {/* ---- user engagement ---- */}
      <h2 className="section-title" style={{ marginTop: 28 }}>Users</h2>
      {!users ? (
        <div className="muted pad">Loading…</div>
      ) : (
        <>
          <div className="metric-cards">
            <div className="metric-card card">
              <div className="metric-label">Users</div>
              <div className="metric-big">{users.totals.user_count}</div>
              <span className="muted small">{users.totals.active_users} have logged in</span>
            </div>
            <div className="metric-card card">
              <div className="metric-label">Avg topics / user</div>
              <div className="metric-big">{users.totals.avg_topics}</div>
            </div>
          </div>
          <p className="muted small">Click a user for their breakdown.</p>
          <div className="metric-table card wide">
            <table>
              <thead>
                <tr>
                  <th>User</th><th>Role</th><th>Last seen</th><th>Topics</th>
                  <th>Tokens</th><th>Clicks</th><th>Votes</th><th>Saves</th><th>Chats</th>
                </tr>
              </thead>
              <tbody>
                {users.users.map((u) => (
                  <tr key={u.id} className="row-click" onClick={() => setSelected(u.id)}>
                    <td>
                      {u.name}
                      {u.status === "disabled" && <span className="chip danger">disabled</span>}
                    </td>
                    <td>{u.role}</td>
                    <td>{u.last_login_at ? timeAgo(u.last_login_at) : "never"}</td>
                    <td>{u.topics}</td>
                    <td>{num(u.tokens)}</td>
                    <td>{u.clicks}</td>
                    <td>{u.votes}</td>
                    <td>{u.saves}</td>
                    <td>{u.chats}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {selected != null && (
        <UserDrawer id={selected} range={range} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}

function UserDrawer({
  id,
  range,
  onClose,
}: {
  id: number;
  range: string;
  onClose: () => void;
}) {
  const push = useToasts((s) => s.push);
  const [detail, setDetail] = useState<UserDetail | null>(null);

  useEffect(() => {
    let cancelled = false;
    setDetail(null);
    api
      .adminUserDetail(id, range)
      .then((d) => !cancelled && setDetail(d))
      .catch((e) => push(String(e), "error"));
    return () => {
      cancelled = true;
    };
  }, [id, range, push]);

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer" aria-label="User detail">
        <div className="drawer-head">
          <h3>{detail?.user.name ?? "User"}</h3>
          <button className="hamburger" onClick={onClose} aria-label="Close">
            <CloseIcon />
          </button>
        </div>
        {!detail ? (
          <div className="muted pad">Loading…</div>
        ) : (
          <div className="drawer-body">
            <p className="muted small">{detail.user.email} · {detail.user.role}</p>

            <div className="metric-cards">
              <div className="metric-card card">
                <div className="metric-label">Tokens ({detail.range})</div>
                <div className="metric-big">{num(detail.usage.tokens)}</div>
                <span className="muted small">{usd(detail.usage.cost)} est.</span>
              </div>
              <div className="metric-card card">
                <div className="metric-label">Logins</div>
                <div className="metric-big">{detail.access.logins}</div>
                <span className="muted small">{detail.access.active_days} active days</span>
              </div>
              <div className="metric-card card">
                <div className="metric-label">Feedback</div>
                <div className="metric-big">👍 {detail.feedback.up} · 👎 {detail.feedback.down}</div>
              </div>
            </div>

            <h4>Where their tokens went</h4>
            <table className="mini-table">
              <thead><tr><th>What</th><th>Tokens</th><th>Cost</th></tr></thead>
              <tbody>
                {detail.usage.by_purpose.map((p) => (
                  <tr key={p.purpose}>
                    <td>{p.label}</td>
                    <td>{num(p.tokens)}</td>
                    <td>{usd(p.cost)}</td>
                  </tr>
                ))}
                {detail.usage.by_purpose.length === 0 && (
                  <tr><td colSpan={3} className="muted">No usage in range.</td></tr>
                )}
              </tbody>
            </table>

            <h4>Subscriptions ({detail.subscriptions.length})</h4>
            <div className="chip-row">
              {detail.subscriptions.map((s) => (
                <span key={s.slug} className="chip">{s.name}</span>
              ))}
              {detail.subscriptions.length === 0 && <span className="muted small">None.</span>}
            </div>

            {detail.feedback.recent.length > 0 && (
              <>
                <h4>Recent votes</h4>
                <ul className="vote-list">
                  {detail.feedback.recent.map((v) => (
                    <li key={v.item_id}>
                      <span>{v.vote > 0 ? "👍" : "👎"}</span>{" "}
                      {v.url ? (
                        <a href={v.url} target="_blank" rel="noreferrer">{v.title}</a>
                      ) : (
                        <span>{v.title}</span>
                      )}
                      <span className="muted small"> · {v.source_name}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        )}
      </aside>
    </>
  );
}
