import type { QueryConditions, QuerySnapshot, RailWatchConfig, RailWatchStatus } from "../types";
import { getDateRangeStatus } from "./tripDate";

export type QueryView = { owner: string; latest: QuerySnapshot; success: QuerySnapshot | null };
export type QueryViews = Record<string, QueryView>;

export function queryTargets(value: string) {
  return [...new Set(value.trim().split(/[,，、;；\s]+/).filter(Boolean))];
}

export function queryFamily(config: RailWatchConfig) {
  return JSON.stringify([config.from_station_cn.trim(), config.to_station_cn.trim(), config.date, config.date_range,
    queryTargets(config.train_code.toUpperCase()), queryTargets(config.seat_keyword)]);
}

export function snapshotMatches(snapshot: QuerySnapshot, config: RailWatchConfig) {
  return snapshot.schema_version === 1 && Number.isSafeInteger(snapshot.sequence) && snapshot.sequence >= 0 &&
    conditionsMatch(snapshot.conditions, config);
}

export function queryRouteMatches(c: QueryConditions, config: RailWatchConfig) {
  const dates = getDateRangeStatus(config.date, config.date_range);
  return c.from_station === config.from_station_cn.trim() && c.to_station === config.to_station_cn.trim() &&
    [...dates.valid, ...dates.skipped].includes(c.date);
}

export function selectableQueryTrains(views: QueryViews, config: RailWatchConfig) {
  return new Set(Object.values(views).filter(view => view.success && queryRouteMatches(view.success.conditions, config))
    .flatMap(view => view.success!.rows.map(row => row.train)));
}

export function conditionsMatch(c: QueryConditions, config: RailWatchConfig) {
  return queryRouteMatches(c, config) &&
    JSON.stringify(c.train_codes) === JSON.stringify(queryTargets(config.train_code.toUpperCase())) &&
    JSON.stringify(c.seat_types) === JSON.stringify(queryTargets(config.seat_keyword));
}

export function mergeQuerySnapshots(views: QueryViews, snapshots: QuerySnapshot[], owner: string, config: RailWatchConfig) {
  const next = { ...views };
  let accepted = false;
  for (const snapshot of snapshots) {
    if (!snapshotMatches(snapshot, config)) continue;
    const c = snapshot.conditions;
    const key = JSON.stringify([c.from_station, c.to_station, c.date, c.train_codes, c.seat_types]);
    const current = next[key];
    if (current?.owner === owner && snapshot.sequence <= current.latest.sequence) continue;
    next[key] = { owner, latest: snapshot, success: snapshot.status === "success" ? snapshot : current?.success ?? null };
    accepted = true;
  }
  return { views: next, accepted };
}

export function queryRows(views: QueryViews) {
  return Object.values(views).sort((a, b) => a.latest.conditions.date.localeCompare(b.latest.conditions.date))
    .flatMap(view => view.success?.rows ?? []);
}

export function queryFreshness(view: QueryView, status: RailWatchStatus, config: RailWatchConfig, now: number, manualPending = false) {
  if (view.latest.status === "error") return view.success ? "本轮查询失败 · 显示上次成功结果" : "本轮查询失败 · 尚无成功结果";
  if (!view.success) return "尚无成功结果";
  if (manualPending) return "正在查询 · 显示上次成功结果";
  if (!status.monitoring) return "上次成功结果 · 当前未监控";
  if (["error", "human_action", "stopping", "verification", "unknown"].includes(status.task?.status ?? "") || status.error_message)
    return "上次成功结果 · 查询已暂停";
  const days = config.date_range === "±2天" ? 5 : config.date_range === "±1天" ? 3 : 1;
  const cycle = days * (config.query_timeout + config.interval) + 5;
  const overdue = now > (view.success.fetched_at ?? 0) + cycle;
  if (overdue) return "数据已过期 · 显示上次成功结果";
  if ((status.task?.next_query_at ?? 0) > now) return "等待下一轮 · 最近成功结果";
  return "查询中 · 上次成功结果";
}
