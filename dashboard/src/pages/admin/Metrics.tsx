import { useEffect, useState } from "react";
import InsightsIcon from "@mui/icons-material/InsightsOutlined";
import TrendingUpIcon from "@mui/icons-material/TrendingUp";
import TrendingDownIcon from "@mui/icons-material/TrendingDown";
import { api, type LlmMetrics, type UserMetrics } from "../../api";
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
          </div>

          <p className="muted small">
            Estimated from token volume × list price — a cost trend, not an invoice.
          </p>

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
                      <td>{t.name}</td>
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
                  <tr key={u.id}>
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
    </div>
  );
}
