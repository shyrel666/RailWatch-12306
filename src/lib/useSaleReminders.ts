import { useCallback, useEffect, useState } from "react";
import type { SaleReminderList } from "../types";
import { railwatchApi } from "./railwatchApi";

function valid(value: unknown): value is SaleReminderList {
  const list = value as SaleReminderList | null;
  return Boolean(list && Array.isArray(list.items) && typeof list.lead_minutes === "number");
}

/** Loads only once a route is set, so an empty trip sends no request. */
export function useSaleReminders(enabled: boolean) {
  const [list, setList] = useState<SaleReminderList | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    void railwatchApi.command<SaleReminderList>("saleReminders")
      .then(next => { if (alive && valid(next)) setList(next); })
      .catch(() => { if (alive) setError("起售提醒暂不可用。"); });
    return () => { alive = false; };
  }, [enabled]);

  const run = useCallback(async (command: string, payload: Record<string, unknown>) => {
    setBusy(true);
    setError("");
    try {
      const next = await railwatchApi.command<SaleReminderList>(command, payload);
      if (!valid(next)) throw new Error("起售提醒未保存，请重试。");
      setList(next);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "起售提醒未保存，请重试。");
    } finally {
      setBusy(false);
    }
  }, []);

  return {
    list, busy, error,
    add: (from_station: string, to_station: string, date: string) => run("addSaleReminder", { from_station, to_station, date }),
    remove: (id: string) => run("removeSaleReminder", { id }),
  };
}
