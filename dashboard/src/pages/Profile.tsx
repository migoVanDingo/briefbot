import { useEffect, useRef, useState } from "react";
import PersonIcon from "@mui/icons-material/PersonOutlined";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import ArticleIcon from "@mui/icons-material/ArticleOutlined";
import { api, type Profile as ProfileData } from "../api";
import { useToasts } from "../state/toasts";
import { useAuth } from "../state/auth";

const usd = (n: number) => `$${n.toFixed(n < 1 ? 4 : 2)}`;
const num = (n: number) => n.toLocaleString();
const WINDOWS: { key: "day" | "week" | "month" | "year" | "all"; label: string }[] = [
  { key: "day", label: "Today" },
  { key: "week", label: "This week" },
  { key: "month", label: "This month" },
  { key: "year", label: "This year" },
  { key: "all", label: "All time" },
];

export function Profile() {
  const push = useToasts((s) => s.push);
  const [data, setData] = useState<ProfileData | null>(null);
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  // Shared cache-bust token so BOTH this page's avatar and the topbar's refresh
  // after a generation/reset (bumped in the store).
  const avatarV = useAuth((s) => s.avatarVersion);
  const bumpAvatar = useAuth((s) => s.bumpAvatar);
  const pollRef = useRef<number | null>(null);
  const mounted = useRef(true);

  const reload = () =>
    api.profile().then((p) => mounted.current && setData(p)).catch((e) => push(String(e), "error"));

  useEffect(() => {
    mounted.current = true;
    reload();
    return () => {
      mounted.current = false;
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // While an avatar is generating, poll until it settles (ready/error/none).
  useEffect(() => {
    if (data?.user.avatar_status !== "pending") return;
    pollRef.current = window.setInterval(async () => {
      try {
        const p = await api.profile();
        if (!mounted.current) return;
        setData(p);
        if (p.user.avatar_status !== "pending") {
          if (pollRef.current) window.clearInterval(pollRef.current);
          bumpAvatar();
          if (p.user.avatar_status === "error") push("Avatar generation failed.", "error");
        }
      } catch {
        /* keep polling */
      }
    }, 2500);
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, [data?.user.avatar_status, push, bumpAvatar]);

  const generate = async () => {
    const p = prompt.trim();
    if (!p) return;
    setBusy(true);
    try {
      await api.generateAvatar(p);
      setPrompt("");
      await reload(); // status flips to pending → poll takes over
    } catch (e) {
      push(String(e), "error");
    } finally {
      setBusy(false);
    }
  };

  const reset = async () => {
    try {
      await api.resetAvatar();
      await reload();
      bumpAvatar();
    } catch (e) {
      push(String(e), "error");
    }
  };

  if (!data) return <div className="muted pad">Loading…</div>;

  const pending = data.user.avatar_status === "pending";

  return (
    <div className="page">
      <h1 className="page-title">
        <PersonIcon className="title-ico" /> Profile
      </h1>

      <div className="profile-grid">
        {/* ---- avatar ---- */}
        <div className="card profile-avatar-card">
          <div className={`avatar-wrap${pending ? " loading" : ""}`}>
            <img
              className="avatar-img"
              src={api.avatarUrl(data.user.id, avatarV)}
              alt="Your avatar"
              width={120}
              height={120}
            />
            {pending && <div className="avatar-spinner" aria-label="Generating…" />}
          </div>
          <div className="profile-id">
            <strong>{data.user.name}</strong>
            <span className="muted small">{data.user.email}</span>
            <span className="chip">{data.user.role}</span>
          </div>

          {data.avatars_enabled ? (
            <div className="avatar-gen">
              <label className="muted small" htmlFor="avatar-prompt">
                Generate an avatar from a prompt
              </label>
              <textarea
                id="avatar-prompt"
                rows={2}
                maxLength={300}
                placeholder="e.g. a friendly fox reading a newspaper, flat vector"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                disabled={pending || busy}
              />
              <div className="avatar-actions">
                <button
                  className="btn primary icon-btn-text"
                  onClick={generate}
                  disabled={pending || busy || !prompt.trim()}
                >
                  <AutoAwesomeIcon fontSize="small" />
                  {pending ? "Generating…" : "Generate"}
                </button>
                {(data.user.avatar_status === "ready" ||
                  data.user.avatar_status === "error") && (
                  <button className="btn ghost" onClick={reset} disabled={busy}>
                    Reset to default
                  </button>
                )}
              </div>
            </div>
          ) : (
            <p className="muted small">Avatar generation is currently unavailable.</p>
          )}
        </div>

        {/* ---- personal metrics ---- */}
        <div className="profile-main">
          <h2 className="section-title">Your usage</h2>
          <div className="metric-cards">
            {WINDOWS.map((w) => (
              <div key={w.key} className="metric-card card">
                <div className="metric-label">{w.label}</div>
                <div className="metric-big">{num(data.usage[w.key].tokens)}</div>
                <span className="muted small">{usd(data.usage[w.key].cost)} est. · tokens</span>
              </div>
            ))}
          </div>
          <p className="muted small">Estimated cost from token volume — a trend, not an invoice.</p>

          <h2 className="section-title" style={{ marginTop: 22 }}>
            Subscriptions ({data.subscriptions.length})
          </h2>
          <div className="chip-row">
            {data.subscriptions.map((s) => (
              <span key={s.slug} className="chip">{s.name}</span>
            ))}
            {data.subscriptions.length === 0 && (
              <span className="muted small">No topics yet — add one from Topics or Chat.</span>
            )}
          </div>

          {/* ---- blogs (stub) ---- */}
          <h2 className="section-title" style={{ marginTop: 22 }}>
            <ArticleIcon fontSize="small" style={{ verticalAlign: "-3px" }} /> Blogs
          </h2>
          <div className="card stub-card">
            <p className="muted">
              Soon you'll be able to write and publish blog posts in your space.
            </p>
            <button className="btn" disabled title="Coming soon">
              New post
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
