import { useEffect, useState } from "react";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";
import { Joyride, STATUS, type Step } from "react-joyride";
import { TOURS } from "../lib/tours";
import { useAuth } from "../state/auth";

// Renders the ⓘ relaunch button (next to a page title) and the page's Joyride.
// Auto-runs once per ACCOUNT on first visit (server-side flag, 0018), so it no
// longer replays after a storage clear or in a new browser. `ready` defers the
// auto-run until the page's tour targets are actually on screen.
export function PageTour({ page, ready = true }: { page: string; ready?: boolean }) {
  const def = TOURS[page];
  const flag = `tour:${page}`;
  const hasFlag = useAuth((s) => s.hasFlag);
  const setFlag = useAuth((s) => s.setFlag);
  const [run, setRun] = useState(false);

  useEffect(() => {
    if (!def || !ready) return;
    if (!hasFlag(flag)) setRun(true);
  }, [def, ready, flag, hasFlag]);

  if (!def) return null;

  const onEvent = (data: { status: string }) => {
    if (data.status === STATUS.FINISHED || data.status === STATUS.SKIPPED) {
      setRun(false);
      setFlag(flag); // persist "seen" to the account
    }
  };

  return (
    <>
      <button
        className="info-btn"
        type="button"
        onClick={() => setRun(true)}
        aria-label={`Launch ${def.label} tutorial`}
        title={`Launch ${def.label} tutorial`}
      >
        <InfoOutlinedIcon fontSize="small" />
      </button>
      <Joyride
        steps={def.steps as Step[]}
        run={run}
        continuous
        onEvent={onEvent}
        options={{
          primaryColor: "#7c5cff",
          zIndex: 10000,
          showProgress: true,
          skipBeacon: true,
          // Clear the ~58px sticky topbar when scrolling a step into view, so
          // targets (the headline, the ⓘ button) don't end up hidden under it.
          scrollOffset: 100,
          buttons: ["skip", "back", "primary"],
        }}
      />
    </>
  );
}
