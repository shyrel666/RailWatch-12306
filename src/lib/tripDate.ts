import { useEffect, useState } from "react";

// Fallback for older runtimes; the active policy is supplied by Python.
export const PRESALE_WINDOW_DAYS = 15;
export const MAX_CUSTOM_DATES = 5;
const DAY = 86_400_000;
export type TripDateStatus = { daysFromToday: number | null; expired: boolean; beyondPresale: boolean; warning: string | null };

export function todayIso(today: Date = new Date()): string {
  return new Date(today.getTime() + 8 * 3_600_000).toISOString().slice(0, 10);
}

function dayNumber(value: string): number | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith("0000-")) return null;
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

export function orderedCustomDates(date: string, customDates: string[] = []): string[] {
  const dates = date && !customDates.includes(date) ? [date, ...customDates] : customDates;
  return [...new Set(dates)].slice(0, MAX_CUSTOM_DATES);
}

export function expandTripDates(date: string, range: string, customDates?: string[]): string[] {
  const base = dayNumber(date);
  if (base === null) return [];
  if (range === "自定义") {
    if (customDates?.some(value => dayNumber(value) === null)) return [];
    return orderedCustomDates(date, customDates);
  }
  const radius = range === "±2天" ? 2 : range === "±1天" ? 1 : 0;
  return Array.from({ length: 2 * radius + 1 }, (_, i) => new Date((base + i - radius) * DAY).toISOString().slice(0, 10));
}

export function getDateRangeStatus(date: string, range: string, today = new Date(), windowDays = PRESALE_WINDOW_DAYS,
  customDates?: string[]) {
  const dates = expandTripDates(date, range, customDates);
  const valid: string[] = [], skipped: string[] = [];
  for (const value of dates) {
    const status = getTripDateStatus(value, today, windowDays);
    (status.expired || status.beyondPresale ? skipped : valid).push(value);
  }
  return { valid, skipped, invalid: dates.length === 0 };
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
