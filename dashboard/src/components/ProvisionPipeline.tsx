// Pipeline stage tracker for topic provisioning. Each step is waiting / in-
// progress / complete, driven by the SSE `stage` events.
const STEPS = [
  { key: "discovering", label: "Discover" },
  { key: "approving", label: "Approve" },
  { key: "collecting", label: "Collect" },
  { key: "reviewing", label: "Review" },
  { key: "summarizing", label: "Summarize" },
  { key: "ready", label: "Ready" },
];
const ORDER = STEPS.map((s) => s.key);

export function ProvisionPipeline({
  stage,
  failed = false,
}: {
  stage: string | null;
  failed?: boolean;
}) {
  const current = stage ? ORDER.indexOf(stage) : -1;
  return (
    <div className="pipeline">
      {STEPS.map((s, i) => {
        const state =
          current > i || (current === i && s.key === "ready" && !failed)
            ? "done"
            : current === i
              ? failed
                ? "failed"
                : "active"
              : "wait";
        const mark =
          state === "done"
            ? "✓"
            : state === "failed"
              ? "✕"
              : state === "active"
                ? "●"
                : "○";
        return (
          <div key={s.key} className="pipe-step">
            <span className={`pipe-chip ${state}`}>
              <span className="pipe-mark">{mark}</span>
              {s.label}
            </span>
            {i < STEPS.length - 1 && <span className="pipe-arrow">→</span>}
          </div>
        );
      })}
    </div>
  );
}
