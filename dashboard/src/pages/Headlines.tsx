import { useEffect, useState } from "react";
import ArticleIcon from "@mui/icons-material/ArticleOutlined";
import TrendingUpIcon from "@mui/icons-material/TrendingUp";
import { api, type Brief, type Story, type TopicTab } from "../api";
import { useToasts } from "../state/toasts";
import { StoryRow } from "../components/StoryRow";
import { LoadingBanner } from "../components/LoadingBanner";

const TODAY = "__today__";
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

export function Headlines() {
  const push = useToasts((s) => s.push);
  const [tabs, setTabs] = useState<TopicTab[]>([]);
  const [briefs, setBriefs] = useState<Brief[] | null>(null);
  const [active, setActive] = useState<string>(TODAY);
  const [stories, setStories] = useState<Story[] | null>(null);
  // The topic tab's rundown: "loading" while building, Brief when ready, null if none.
  const [rundown, setRundown] = useState<Brief | "loading" | null>(null);

  useEffect(() => {
    api
      .briefs()
      .then((d) => {
        setBriefs(d.briefs);
        setTabs(d.topics);
      })
      .catch((e) => {
        push(String(e), "error");
        setBriefs([]);
      });
  }, [push]);

  // A topic tab shows that topic's rundown (built once per day, shared) above its
  // stories (newest first), with votes + save.
  useEffect(() => {
    if (active === TODAY) return;
    setStories(null);
    setRundown("loading");
    api
      .topicRundown(active)
      .then((d) => setRundown(d.rundown))
      .catch(() => setRundown(null));
    api
      .queryStories({ topic: active, limit: 50 })
      .then(setStories)
      .catch((e) => {
        push(String(e), "error");
        setStories([]);
      });
  }, [active, push]);

  return (
    <div className="page">
      <h1 className="page-title">
        <ArticleIcon className="title-ico" /> Headlines
      </h1>

      <div className="tabs">
        <button
          className={`tab${active === TODAY ? " active" : ""}`}
          onClick={() => setActive(TODAY)}
        >
          Today
        </button>
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

      {active === TODAY ? (
        briefs === null ? (
          <div className="muted pad">Loading brief…</div>
        ) : briefs.length === 0 ? (
          <div className="empty">
            <h2>Your briefing is being prepared</h2>
            <p className="muted">
              Head to <b>Chat</b> and tell Briefbot a subject to follow, or create
              one on the <b>Topics</b> page. Your morning brief lands here once a
              topic has stories.
            </p>
          </div>
        ) : (
          briefs.map((b) => <BriefCard key={b.topic_slug} brief={b} />)
        )
      ) : (
        <>
          {rundown === "loading" ? (
            <LoadingBanner phrases={RUNDOWN_PHRASES} />
          ) : rundown ? (
            <BriefCard brief={rundown} />
          ) : null}
          {stories === null ? (
            <div className="muted pad">Loading…</div>
          ) : stories.length === 0 ? (
            <div className="empty">
              <h2>No stories yet</h2>
              <p className="muted">Nothing collected for this topic yet.</p>
            </div>
          ) : (
            <ul className="story-list">
              {stories.map((s) => (
                <StoryRow key={s.item_id} story={s} />
              ))}
            </ul>
          )}
        </>
      )}
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

      {brief.trending.length > 0 && (
        <div className="brief-section">
          <h2 className="section-title">
            <TrendingUpIcon className="sec-ico" /> Trending
          </h2>
          <ul className="list">
            {brief.trending.map((t, i) => (
              <li key={i} className="list-row">
                <div className="src-info">
                  <div className="list-title">{t.label}</div>
                  {t.representative_title && (
                    <a
                      className="muted small"
                      href={t.representative_url ?? "#"}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {t.representative_title}
                    </a>
                  )}
                </div>
                <span className="chip">
                  {t.item_count} {t.item_count === 1 ? "story" : "stories"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {brief.sources.length > 0 && (
        <div className="brief-section">
          <h2 className="section-title">Sources</h2>
          <ul className="story-list">
            {brief.sources.map((s, i) => (
              <StoryRow
                key={s.item_id ?? i}
                story={{
                  item_id: s.item_id ?? "",
                  title: s.title,
                  url: s.url,
                  source_name: s.source_name,
                }}
              />
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
