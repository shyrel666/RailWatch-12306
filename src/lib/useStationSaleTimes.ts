import { useCallback, useEffect, useRef, useState } from "react";
import type { StationSaleTimes } from "../types";
import { railwatchApi } from "./railwatchApi";

export function useStationSaleTimes(station: string) {
  const [result, setResult] = useState<StationSaleTimes | null>(null);
  const [loading, setLoading] = useState(false);
  const [failure, setFailure] = useState<{ station: string; message: string } | null>(null);
  const refreshRef = useRef<(force: boolean) => void>(() => {});

  useEffect(() => {
    let active = true;
    let pending = false;
    let refreshAfter = 0;
    setResult(null);
    setFailure(null);
    setLoading(false);
    const load = async (force = false) => {
      if (!station || pending || (!force && Date.now() < refreshAfter)) return;
      pending = true;
      setLoading(true);
      try {
        const next = await railwatchApi.command<StationSaleTimes>("stationSaleTimes", { station, force });
        if (!next || next.station !== station || !Array.isArray(next.schedules)
            || !["available", "not_found", "stale", "unavailable"].includes(next.status)) {
          throw new Error("Invalid sale-time response");
        }
        if (!active) return;
        setResult(next);
        setFailure(null);
        refreshAfter = Math.max(Date.now() + 60_000,
          next.warning ? next.retry_at * 1000 : (next.expires_at || next.retry_at) * 1000);
      } catch {
        if (!active) return;
        setFailure({ station, message: "起售时间暂不可用，请稍后刷新或前往官方核对。" });
        refreshAfter = Date.now() + 60_000;
      } finally {
        pending = false;
        if (active) setLoading(false);
      }
    };
    refreshRef.current = force => { void load(force); };
    void load();
    const update = () => { if (document.visibilityState !== "hidden") void load(); };
    const timer = window.setInterval(update, 60_000);
    window.addEventListener("focus", update);
    document.addEventListener("visibilitychange", update);
    return () => {
      active = false;
      window.clearInterval(timer);
      window.removeEventListener("focus", update);
      document.removeEventListener("visibilitychange", update);
    };
  }, [station]);

  const refresh = useCallback(() => refreshRef.current(true), []);
  return { info: result?.station === station ? result : null, loading,
    error: failure?.station === station ? failure.message : null, refresh };
}
