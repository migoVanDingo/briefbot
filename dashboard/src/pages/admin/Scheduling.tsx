import { useEffect, useState } from "react";
import ScheduleIcon from "@mui/icons-material/ScheduleOutlined";
import SaveIcon from "@mui/icons-material/SaveOutlined";
import ReplayIcon from "@mui/icons-material/ReplayOutlined";
import {
  api,
  type ScheduleDefaults,
  type TopicSchedule,
  type DiscoverPeriod,
  type SchedulePatch,
} from "../../api";
import { AdminNav } from "../../components/AdminNav";
import { useToasts } from "../../state/toasts";
import { timeAgo } from "../../lib/format";

const PERIODS: { value: DiscoverPeriod; label: string }[] = [
  { value: "day", label: "Day" },
  { value: "week", label: "Week" },
  { value: "month", label: "Month" },
  { value: "year", label: "Year" },
];

const pad = (n: number) => String(n).padStart(2, "0");
const minToHHMM = (m: number | null, fallback = "23:00") =>
  m == null ? fallback : `${pad(Math.floor(m / 60))}:${pad(m % 60)}`;
const hhmmToMin = (s: string) => {
  const [h, m] = s.split(":").map(Number);
  return (h || 0) * 60 + (m || 0);
};
const todayISO = () => new Date().toISOString().slice(0, 10);
const orClear = (v: string) => (v.trim() === "" ? -1 : Number(v));

function Row({
  topic,
  defaults,
  onSaved,
}: {
  topic: TopicSchedule;
  defaults: ScheduleDefaults;
  onSaved: () => void;
}) {
  const push = useToasts((s) => s.push);
  const configured = topic.discover.period != null;
  const [period, setPeriod] = useState<DiscoverPeriod>(topic.discover.period ?? "week");
  const [start, setStart] = useState(topic.discover.start_date ?? todayISO());
  const [time, setTime] = useState(minToHHMM(topic.discover.at_min));
  // collect interval shown as H : MM
  const ci = topic.collect.interval_min;
  const [collH, setCollH] = useState(ci == null ? "" : String(Math.floor(ci / 60)));
  const [collM, setCollM] = useState(ci == null ? "" : String(ci % 60));
  const [maxSrc, setMaxSrc] = useState(topic.caps.max_sources?.toString() ?? "");
  const [maxStory, setMaxStory] = useState(
    topic.caps.max_stories_per_source?.toString() ?? "",
  );
  const [busy, setBusy] = useState(false);

  const defH = Math.floor(defaults.collect_interval_min / 60);
  const defM = defaults.collect_interval_min % 60;

  const save = async () => {
    setBusy(true);
    const collBlank = collH.trim() === "" && collM.trim() === "";
    const body: SchedulePatch = {
      discover_period: period,
      discover_start_date: start,
      discover_at_min: hhmmToMin(time),
      collect_interval_min: collBlank
        ? -1
        : (Number(collH || 0) * 60 + Number(collM || 0)),
      max_sources: orClear(maxSrc),
      max_stories_per_source: orClear(maxStory),
    };
    try {
      await api.setTopicSchedule(topic.slug, body);
      push(`Saved ${topic.name}`, "success");
      onSaved();
    } catch (e) {
      push(String(e), "error");
    } finally {
      setBusy(false);
    }
  };

  const reset = async () => {
    setBusy(true);
    try {
      await api.resetTopicSchedule(topic.slug);
      push(`Reset ${topic.name} to defaults`, "info");
      onSaved();
    } catch (e) {
      push(String(e), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="sched-row card">
      <div className="sched-name">
        <strong>{topic.name}</strong>
        <span className="muted small">
          {topic.last_discovered_at
            ? `discovered ${timeAgo(topic.last_discovered_at)}`
            : "never discovered"}
        </span>
      </div>

      <div className="sched-group">
        <label className="sched-label">
          Discover {!configured && <span className="muted small">(default)</span>}
        </label>
        <span className="muted small">every</span>
        <select value={period} onChange={(e) => setPeriod(e.target.value as DiscoverPeriod)}>
          {PERIODS.map((p) => (
            <option key={p.value} value={p.value}>
              {p.label}
            </option>
          ))}
        </select>
        <span className="muted small">starting</span>
        <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
        <span className="muted small">at</span>
        <input type="time" value={time} onChange={(e) => setTime(e.target.value)} />
        <span className="muted small">UTC</span>
      </div>

      <div className="sched-group">
        <label className="sched-label">Collect</label>
        <span className="muted small">every</span>
        <input
          type="number"
          min={0}
          className="hm"
          value={collH}
          placeholder={`${defH}`}
          onChange={(e) => setCollH(e.target.value)}
          title="hours"
        />
        <span>:</span>
        <input
          type="number"
          min={0}
          max={59}
          className="hm"
          value={collM}
          placeholder={pad(defM)}
          onChange={(e) => setCollM(e.target.value)}
          title="minutes"
        />
        <span className="muted small">hrs:min</span>
      </div>

      <div className="sched-group">
        <label className="sched-label">Caps</label>
        <input
          type="number"
          min={1}
          className="hm"
          value={maxSrc}
          placeholder={`${defaults.max_sources}`}
          onChange={(e) => setMaxSrc(e.target.value)}
          title="max sources (blank = default)"
        />
        <span className="muted small">srcs ·</span>
        <input
          type="number"
          min={1}
          className="hm"
          value={maxStory}
          placeholder={`${defaults.max_stories_per_source}`}
          onChange={(e) => setMaxStory(e.target.value)}
          title="max stories per source (blank = default)"
        />
        <span className="muted small">stories</span>
      </div>

      <div className="sched-actions">
        <button className="btn primary icon-btn-text" onClick={save} disabled={busy}>
          <SaveIcon fontSize="small" /> Save
        </button>
        <button className="btn ghost" onClick={reset} disabled={busy}>
          Reset
        </button>
      </div>
    </div>
  );
}

export function Scheduling() {
  const push = useToasts((s) => s.push);
  const [data, setData] = useState<{
    defaults: ScheduleDefaults;
    topics: TopicSchedule[];
  } | null>(null);

  const load = () =>
    api
      .adminSchedule()
      .then(setData)
      .catch((e) => push(String(e), "error"));

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const resetAll = async () => {
    try {
      await api.resetAllSchedules();
      push("All topics reset to defaults", "info");
      load();
    } catch (e) {
      push(String(e), "error");
    }
  };

  return (
    <div className="page">
      <h1 className="page-title">
        <ScheduleIcon className="title-ico" /> Scheduling
      </h1>
      <AdminNav />
      <p className="muted">
        Discover finds new sources; collect pulls fresh stories from them. Times are
        UTC and the heartbeat runs every {data?.defaults.window_min ?? 15} min (the
        finest granularity). Blank caps use the default.
      </p>

      {!data ? (
        <div className="muted pad">Loading…</div>
      ) : (
        <>
          <div className="sched-toolbar">
            <button className="btn ghost icon-btn-text" onClick={resetAll}>
              <ReplayIcon fontSize="small" /> Reset all to defaults
            </button>
          </div>
          {data.topics.length === 0 ? (
            <div className="muted pad">No topics yet.</div>
          ) : (
            data.topics.map((t) => (
              <Row key={t.slug} topic={t} defaults={data.defaults} onSaved={load} />
            ))
          )}
        </>
      )}
    </div>
  );
}
