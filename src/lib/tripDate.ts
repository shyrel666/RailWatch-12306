import { useEffect, useState } from "react";

// Fallback for older runtimes; the active policy is supplied by Python.
export const PRESALE_WINDOW_DAYS = 15;
const DAY = 86_400_000;
export type TripDateStatus = { daysFromToday: number | null; expired: boolean; beyondPresale: boolean; warning: string | null };

export function todayIso(today: Date = new Date()): string {
  return new Date(today.getTime() + 8 * 3_600_000).toISOString().slice(0, 10);
}

function dayNumber(value: string): number | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const timestamp = Date.parse(`${value}T00:00:00Z`);
  return Number.isFinite(timestamp) && new Date(timestamp).toISOString().slice(0, 10) === value ? timestamp / DAY : null;
}

export function getTripDateStatus(date: string, today = new Date(), windowDays = PRESALE_WINDOW_DAYS): TripDateStatus {
  const parsed = dayNumber((date || "").trim());
  const neutral = { daysFromToday: null, expired: false, beyondPresale: false, warning: null };
  if (parsed === null) return neutral;
  const daysFromToday = parsed - dayNumber(todayIso(today))!;
  return {
    daysFromToday, expired: daysFromToday < 0, beyondPresale: daysFromToday >= windowDays,
    warning: daysFromToday < 0 ? "出发日期已过去，请更新后再查询或监控" : daysFromToday >= windowDays ? `超出预售期（${windowDays} 天），暂无法查询该日期` : null,
  };
}

export function isoDaysFromToday(offsetDays: number, today = new Date()): string {
  return new Date((dayNumber(todayIso(today))! + offsetDays) * DAY).toISOString().slice(0, 10);
}

export function getDateRangeStatus(date: string, range: string, today = new Date(), windowDays = PRESALE_WINDOW_DAYS) {
  const base = dayNumber(date);
  const valid: string[] = [], skipped: string[] = [];
  if (base === null) return { valid, skipped, invalid: true };
  const radius = range === "±2天" ? 2 : range === "±1天" ? 1 : 0;
  for (let offset = -radius; offset <= radius; offset++) {
    const value = new Date((base + offset) * DAY).toISOString().slice(0, 10);
    const status = getTripDateStatus(value, today, windowDays);
    (status.expired || status.beyondPresale ? skipped : valid).push(value);
  }
  return { valid, skipped, invalid: false };
}

export function useBeijingToday() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    const update = () => {
      const current = new Date();
      setNow(current);
      clearTimeout(timer);
      timer = setTimeout(update, DAY - ((current.getTime() + 8 * 3_600_000) % DAY) + 50);
    };
    update();
    window.addEventListener("focus", update);
    document.addEventListener("visibilitychange", update);
    return () => { clearTimeout(timer); window.removeEventListener("focus", update); document.removeEventListener("visibilitychange", update); };
  }, []);
  return now;
}

export function executionReference(config: { timer_enabled: boolean; target_time: string; sale_at?: string }, now: Date) {
  if (!config.timer_enabled || !config.sale_at) return now;
  const target = Date.parse(config.sale_at);
  return Number.isFinite(target) ? new Date(Math.max(target, now.getTime())) : now;
}
