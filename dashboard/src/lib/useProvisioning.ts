import { useCallback, useEffect, useRef, useState } from "react";
import { api, type ProvisionRun } from "../api";

// Poll /api/provisioning for the user's active (+ just-finished) provisioning runs
// (0023). Self-throttles: it only keeps polling while something is `running`, and
// `refresh()` kicks an immediate fetch (e.g. right after a run is started). Pass a
// conversationId to scope to one chat thread.
export function useProvisioning(conversationId?: string) {
  const [runs, setRuns] = useState<ProvisionRun[]>([]);
  const timer = useRef<number | null>(null);
  const alive = useRef(true);

  const clear = () => {
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
  };

  const poll = useCallback(async () => {
    try {
      const r = await api.provisioning(conversationId);
      if (!alive.current) return;
      setRuns(r);
      clear();
      if (r.some((x) => x.status === "running")) {
        timer.current = window.setTimeout(poll, 1200);
      }
    } catch {
      // transient (e.g. a refresh mid-flight) — a later refresh()/trigger retries.
    }
  }, [conversationId]);

  const refresh = useCallback(() => {
    clear();
    void poll();
  }, [poll]);

  useEffect(() => {
    alive.current = true;
    void poll();
    return () => {
      alive.current = false;
      clear();
    };
  }, [poll]);

  return { runs, refresh };
}
