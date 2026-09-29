import type { RailWatchConfig, RailWatchPage } from "../types";

export type RehearsalCheck = {
  id: string; title: string; critical: boolean; required_evidence?: boolean;
  status?: "pass" | "warn" | "fail" | "unknown" | "skipped";
  summary?: string; details?: string[]; duration_ms?: number;
  fix?: { page: RailWatchPage; section: string; label: string; sale_at?: string; checked_at?: number };
};
export type TimelineSegment = { id: string; label: string; duration_ms: number | null; start_ms?: number | null; source: string };
export type RehearsalReport = {
  schema_version: number; rehearsal_id: string; run_id?: string; trigger: "manual" | "task";
  started_at: number; finished_at: number; verdict: "ready" | "risky" | "blocked" | "cancelled";
  trip: { from_station: string; to_station: string; date: string; probe_date?: string; sale_at: string };
  checks: RehearsalCheck[]; measurements: Record<string, unknown>; prediction?: TimelineSegment[];
};
export type RehearsalStarted = { rehearsal_id: string; trigger: "manual" | "task"; checks: RehearsalCheck[] };
export type RunReviewSummary = { run_id: string; started_at: number; target_at: number | null; trip?: Partial<RehearsalReport["trip"]>; conclusion: string };
export type RunReviewDetail = RunReviewSummary & {
  segments: TimelineSegment[]; prediction: TimelineSegment[]; slowest: string | null;
  order_timings?: { kind: "regular" | "alternate"; segments: TimelineSegment[] }[];
  preparation_margin_ms: number | null; query_median_ms: number | null; history_complete: boolean; note: string;
};

export const verdictLabels = { ready: "就绪", risky: "有风险", blocked: "会失败", cancelled: "已取消" };
export const checkLabels = { pass: "通过", warn: "有风险", fail: "会失败", unknown: "无法判断", skipped: "已跳过" };

export function rehearsalExpired(fingerprint: string | null, current: string) {
  return fingerprint === null || fingerprint !== current;
}
export function needsRehearsal(config: RailWatchConfig, report: RehearsalReport | null, stale: boolean) {
  return (config.timer_enabled || config.auto_submit || config.auto_alternate) && (!report || stale || report.verdict !== "ready");
}
export function rehearsalDisabled(config: RailWatchConfig, now: number, monitoring: boolean, pendingOrder: boolean,
  busy: boolean, lastStarted?: number) {
  if (monitoring) return "监控运行中，彩排仅供查看";
  if (pendingOrder) return "请先处理待支付或待核对订单";
  if (busy) return "请等待当前浏览器操作结束";
  if (lastStarted && now / 1000 - lastStarted < 120) return `彩排冷却中，还需 ${Math.max(1, Math.ceil(120 - (now / 1000 - lastStarted)))} 秒`;
  const remaining = config.timer_enabled && config.sale_at ? Date.parse(config.sale_at) - now : Infinity;
  if (remaining >= 0 && remaining < 300_000) return "距离起售不足五分钟，不能运行彩排";
  return "";
}
