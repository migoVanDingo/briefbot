import { useCallback, useEffect, useRef, useState } from "react";
import { api, type DiscoveryRun } from "../api";

// Poll /api/discoveries for the user's on-demand source searches (0030). Mirrors
// useProvisioning: only keeps polling while something is `running`; `refresh()`
// kicks an immediate fetch (e.g. right after a search starts). Scope to one thread
// by passing its conversationId.
export function useDiscoveries(conversationId?: string) {
  const [runs, setRuns] = useState<DiscoveryRun[]>([]);
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
      const r = await api.discoveries(conversationId);
      if (!alive.current) return;
      setRuns(r);
      clear();
      if (r.some((x) => x.status === "running")) {
        timer.current = window.setTimeout(poll, 1500);
      }
    } catch {
      // transient — a later refresh() retries.
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

  return { runs, refresh, setRuns };
}
