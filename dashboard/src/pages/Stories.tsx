import { useCallback, useEffect, useState } from "react";
import FeedIcon from "@mui/icons-material/FeedOutlined";
import SearchIcon from "@mui/icons-material/Search";
import { api, type Story } from "../api";
import { useToasts } from "../state/toasts";
import { StoryRow } from "../components/StoryRow";

type Order = "desc" | "asc";

export function Stories() {
  const push = useToasts((s) => s.push);
  const [sources, setSources] = useState<string[]>([]);
  const [stories, setStories] = useState<Story[] | null>(null);
  const [search, setSearch] = useState("");
  const [source, setSource] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [order, setOrder] = useState<Order>("desc");

  const load = useCallback(async () => {
    setStories(null);
    try {
      const items = await api.queryStories({
        search: search.trim() || undefined,
        source: source || undefined,
        from: from ? `${from}T00:00:00` : undefined,
        to: to ? `${to}T23:59:59` : undefined,
        order,
        limit: 50,
      });
      setStories(items);
    } catch (e) {
      push(String(e), "error");
      setStories([]);
    }
  }, [search, source, from, to, order, push]);

  useEffect(() => {
    api.storySources().then(setSources).catch((e) => push(String(e), "error"));
  }, [push]);

  // Source/date/sort changes reload; free-text search applies on submit.
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source, from, to, order]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    load();
  };

  return (
    <div className="page">
      <h1 className="page-title">
        <FeedIcon className="title-ico" /> Stories
      </h1>

      <form className="filters card" onSubmit={submit}>
        <div className="filter-search">
          <SearchIcon fontSize="small" className="filter-ico" />
          <input
            placeholder="Search title, summary, source…"
            value={search}
            maxLength={100}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <select value={source} onChange={(e) => setSource(e.target.value)}>
          <option value="">All sources</option>
          {sources.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <label className="filter-date">
          From
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label className="filter-date">
          To
          <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        </label>
        <button
          type="button"
          className="btn nowrap"
          onClick={() => setOrder((o) => (o === "desc" ? "asc" : "desc"))}
        >
          {order === "desc" ? "Newest first" : "Oldest first"}
        </button>
        <button className="btn primary nowrap" type="submit">
          Search
        </button>
      </form>

      {stories === null ? (
        <div className="muted pad">Loading stories…</div>
      ) : stories.length === 0 ? (
        <div className="empty">
          <h2>No stories</h2>
          <p className="muted">
            Subscribe to topics and collect their sources to see stories here.
          </p>
        </div>
      ) : (
        <ul className="story-list">
          {stories.map((s) => (
            <StoryRow key={s.item_id} story={s} />
          ))}
        </ul>
      )}
    </div>
  );
}
