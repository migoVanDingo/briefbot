import { useEffect, useState } from "react";
import ArticleIcon from "@mui/icons-material/ArticleOutlined";
import { api, type Brief, type BriefDay, type Story } from "../api";
import { useToasts } from "../state/toasts";
import { useHeadlinesNav } from "../state/headlinesNav";
import { StoryRow } from "../components/StoryRow";
import { LoadingBanner } from "../components/LoadingBanner";

const RUNDOWN_PHRASES = [
  "Reading today's top stories…",
  "Connecting the dots…",
  "Synthesizing your rundown…",
  "Spotting what's trending…",
];

function paragraphs(text: string): string[] {
  return text
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter(Boolean);
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n) + "…" : s;
}

// "2026-06-21" → "Jun 21, 2026" (parse as local midnight so the day never shifts).
function formatDate(date: string): string {
  return new Date(`${date}T00:00:00`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function Headlines() {
  const push = useToasts((s) => s.push);
  // Topic tabs + active slug live in a shared store so the mobile hamburger can
  // drive them too.
  const tabs = useHeadlinesNav((s) => s.topics);
  const active = useHeadlinesNav((s) => s.active);
  const setActive = useHeadlinesNav((s) => s.setActive);
  const setTopics = useHeadlinesNav((s) => s.setTopics);
  const [tabsLoaded, setTabsLoaded] = useState(false);
  const [days, setDays] = useState<BriefDay[] | null>(null); // last 10 calendar days
  const [activeDate, setActiveDate] = useState<string>("");
  // The selected day's brief: "loading" while building today's, Brief when ready,
  // null if that day has none.
  const [rundown, setRundown] = useState<Brief | "loading" | null>(null);
  const [stories, setStories] = useState<Story[] | null>(null);

  // Topic tabs come from the user's subscriptions.
  useEffect(() => {
    api
      .briefs()
      .then((d) => {
        setTopics(d.topics);
        setTabsLoaded(true);
        // Keep a valid active topic; default to the first if none/stale.
        const cur = useHeadlinesNav.getState().active;
        if (!cur || !d.topics.some((t) => t.slug === cur)) {
          setActive(d.topics[0]?.slug ?? "");
        }
      })
      .catch((e) => {
        push(String(e), "error");
        setTopics([]);
        setTabsLoaded(true);
      });
  }, [push, setTopics, setActive]);

  // Switching topic loads its 10-day rail and selects today (the newest day).
  useEffect(() => {
    if (!active) return;
    setDays(null);
    setActiveDate("");
    api
      .topicBriefs(active)
      .then((d) => {
        setDays(d);
        setActiveDate(d[0]?.date ?? "");
      })
      .catch((e) => {
        push(String(e), "error");
        setDays([]);
      });
  }, [active, push]);

  // The selected day's brief. Past days are already in `days`; today's is built
  // on demand (the rundown endpoint caches it, shared across users).
  useEffect(() => {
    if (!active || !activeDate || !days) return;
    const day = days.find((d) => d.date === activeDate);
    if (day?.brief) {
      setRundown(day.brief);
      return;
    }
    if (days[0]?.date !== activeDate) {
      setRundown(null); // a past day with no brief
      return;
    }
    let cancelled = false;
    setRundown("loading");
    api
      .topicRundown(active)
      .then((d) => {
        if (cancelled) return;
        setRundown(d.rundown ?? null);
        if (d.rundown) {
          setDays((prev) =>
            prev
              ? prev.map((x) =>
                  x.date === activeDate ? { ...x, brief: d.rundown! } : x,
                )
              : prev,
          );
        }
      })
      .catch(() => {
        if (!cancelled) setRundown(null);
      });
    return () => {
      cancelled = true;
    };
  }, [active, activeDate, days]);

  // Only the selected day's stories (newest first).
  useEffect(() => {
    if (!active || !activeDate) return;
    setStories(null);
    api
      .queryStories({
        topic: active,
        from: `${activeDate}T00:00:00+00:00`,
        to: `${activeDate}T23:59:59+00:00`,
        limit: 50,
      })
      .then(setStories)
      .catch((e) => {
        push(String(e), "error");
        setStories([]);
      });
  }, [active, activeDate, push]);

  if (!tabsLoaded) return <div className="muted pad">Loading…</div>;

  if (tabs.length === 0) {
    return (
      <div className="page">
        <h1 className="page-title">
          <ArticleIcon className="title-ico" /> Headlines
        </h1>
        <div className="empty">
          <h2>Your briefing is being prepared</h2>
          <p className="muted">
            Head to <b>Chat</b> and tell Briefbot a subject to follow, or create
            one on the <b>Topics</b> page. Your morning brief lands here once a
            topic has stories.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <h1 className="page-title">
        <ArticleIcon className="title-ico" /> Headlines
      </h1>

      <div className="tabs">
        {tabs.map((t) => (
          <button
            key={t.slug}
            className={`tab${active === t.slug ? " active" : ""}`}
            onClick={() => setActive(t.slug)}
          >
            {t.name}
          </button>
        ))}
      </div>

      <div className="headlines-body">
        <aside className="date-rail" aria-label="Past 10 days">
          {(days ?? []).map((d, i) => {
            const isToday = i === 0;
            const clickable = !!d.brief || isToday;
            return (
              <button
                key={d.date}
                className={`date-row${d.date === activeDate ? " active" : ""}`}
                disabled={!clickable}
                onClick={() => setActiveDate(d.date)}
              >
                <span className="date-row-date">{formatDate(d.date)}</span>
                {d.brief ? (
                  <span className="date-row-head">
                    {" "}
                    — {truncate(d.brief.title, 15)}
                  </span>
                ) : isToday ? (
                  <span className="muted small"> · Today</span>
                ) : null}
              </button>
            );
          })}
        </aside>

        <div className="headlines-main">
          {rundown === "loading" ? (
            <LoadingBanner phrases={RUNDOWN_PHRASES} />
          ) : rundown ? (
            <BriefCard brief={rundown} />
          ) : null}
          {stories === null ? (
            <div className="muted pad">Loading…</div>
          ) : stories.length === 0 ? (
            <div className="empty">
              <h2>No stories for this day</h2>
              <p className="muted">Nothing collected for this topic on this date.</p>
            </div>
          ) : (
            <ul className="story-list">
              {stories.map((s) => (
                <StoryRow key={s.item_id} story={s} />
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

function BriefCard({ brief }: { brief: Brief }) {
  return (
    <section className="brief">
      <div className="brief-head">
        <span className="chip">{brief.topic_name}</span>
        <span className="muted small">{brief.date}</span>
      </div>
      <h1 className="brief-title">{brief.title}</h1>
      <div className="brief-summary">
        {paragraphs(brief.summary).map((p, i) => (
          <p key={i}>{p}</p>
        ))}
      </div>
    </section>
  );
}
