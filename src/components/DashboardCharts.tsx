import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import { Button, Tooltip } from "antd";
import { Activity, ArrowRight, CalendarRange } from "lucide-react";
import { msTick, niceTicks } from "../lib/chartScale";
import { railwatchApi } from "../lib/railwatchApi";
import { conclusionTone } from "../lib/runConclusion";
import { isoDaysFromToday, todayIso } from "../lib/tripDate";
import { useRailWatchStore } from "../store/useRailWatchStore";
import type { QueryPulse, QueryPulseItem, RailWatchStatus, RunReviewSummary } from "../types";
import { Hint } from "./DisplayPrimitives";

export const PULSE_LIMIT = 60;
const HISTORY_DAYS = 14;

const shanghai = { timeZone: "Asia/Shanghai", hourCycle: "h23" } as const;
const clock = (at: number, options: Intl.DateTimeFormatOptions = { hour: "2-digit", minute: "2-digit", second: "2-digit" }) =>
  new Intl.DateTimeFormat("zh-CN", { ...shanghai, ...options }).format(new Date(at * 1000));
const pct = (value: number, scale: number) => `${Math.min(100, (value / scale) * 100)}%`;
const secondsText = (ms: number) => `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)} 秒`;
const shortDate = (iso: string) => `${Number(iso.slice(5, 7))}/${Number(iso.slice(8, 10))}`;

const statusLabels: Record<string, string> = {
  ok: "有结果",
  empty: "未返回车次",
  timeout: "查询超时",
  not_on_sale: "尚未起售",
  rate_limited: "查询限频",
  server_backoff: "服务端要求等待",
  human_action: "需要人工处理",
  invalid: "结果已失效",
  cancelled: "已停止",
  unconfirmed: "未完成查询",
};

type PulseKind = "ok" | "hit" | "miss";
function pulseKind(item: QueryPulseItem): PulseKind {
  if (item.hit) return "hit";
  return item.status === "ok" || item.status === "empty" ? "ok" : "miss";
}

function median(values: number[]) {
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

function liveText(status: RailWatchStatus, now: number) {
  if (status.task?.status === "waiting") return "等待定时启动";
  if (status.task?.status === "querying") return "查询中";
  if (status.task?.next_query_at)
    return `下次查询 ${Math.max(0, Math.ceil(status.task.next_query_at - now / 1000))} 秒`;
  return "监控中";
}

// Each finished query is written just after its result is shown, so read shortly after a tick.
function useQueryPulse(monitoring: boolean, loops: number) {
  const [pulse, setPulse] = useState<QueryPulse | null>(null);
  const [failed, setFailed] = useState(false);
  const pending = useRef(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const load = useCallback(async () => {
    if (pending.current) return;
    pending.current = true;
    try {
      const next = await railwatchApi.command<QueryPulse>("queryPulse", { limit: PULSE_LIMIT });
      if (!next || !Array.isArray(next.items)) throw new Error("Invalid query pulse response");
      if (alive.current) {
        setPulse({ ...next, trip: next.trip ?? {} });
        setFailed(false);
      }
    } catch {
      if (alive.current) setFailed(true);
    } finally {
      pending.current = false;
    }
  }, []);
  useEffect(() => {
    const timer = window.setTimeout(() => void load(), loops ? 600 : 0);
    return () => window.clearTimeout(timer);
  }, [load, loops, monitoring]);
  useEffect(() => {
    if (!monitoring) return;
    const timer = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(timer);
  }, [load, monitoring]);
  return { pulse, failed };
}

export function QueryPulseCard({ status, loops, now }: { status: RailWatchStatus; loops: number; now: number }) {
  const navigate = useRailWatchStore((state) => state.setActivePage);
  const { pulse, failed } = useQueryPulse(status.monitoring, loops);
  // While a run is starting, the previous run's queries must not appear under the live indicator.
  const current =
    !status.monitoring ||
    Boolean(pulse?.active && (!status.task?.run_id || pulse.run_id === status.task.run_id));
  const items = current ? pulse?.items ?? [] : [];
  const durations = items.flatMap((item) => (item.duration_ms === null ? [] : [item.duration_ms]));
  const ticks = niceTicks(Math.max(0, ...durations), 3);
  const scale = ticks.at(-1)!;
  const typical = durations.length ? median(durations) : null;
  const valid = items.filter((item) => item.status === "ok" || item.status === "empty").length;
  const hits = items.filter((item) => item.hit).length;
  const recorded = current ? pulse?.recorded ?? 0 : 0;
  const count = status.monitoring ? Math.max(loops, recorded) : recorded;
  const route = pulse?.trip.from_station && pulse.trip.to_station ? ` · ${pulse.trip.from_station}→${pulse.trip.to_station}` : "";
  const lastAt = items.at(-1)?.at;
  return (
    <section className="chart-card pulse-card" aria-label="查询脉搏">
      <div className="section-heading">
        <h2>
          <Activity size={15} aria-hidden="true" /> 查询脉搏
          <Hint text="每根柱是一次查询从准备到判断结果的耗时。监控运行时实时更新，未运行时显示上一次运行。" />
        </h2>
        {status.monitoring ? (
          <span className="chart-meta live" role="status">
            <i className="lamp go live" aria-hidden="true" />
            {liveText(status, now)}
          </span>
        ) : pulse?.run_id && items.length ? (
          <span className="chart-meta">
            上次运行 {clock(pulse.started_at ?? items[0].at, { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}
            {route}
          </span>
        ) : null}
      </div>
      {items.length || status.monitoring ? <dl className="chart-kpis">
        <div>
          <dt>查询次数</dt>
          <dd>{count}</dd>
        </div>
        <div>
          <dt>中位耗时</dt>
          <dd>{typical === null ? "—" : secondsText(typical)}</dd>
        </div>
        <div>
          <dt>有效查询</dt>
          <dd>{items.length ? `${Math.round((valid / items.length) * 100)}%` : "—"}</dd>
        </div>
        <div className={hits ? "is-hit" : undefined}>
          <dt>命中</dt>
          <dd>{hits}</dd>
        </div>
      </dl> : null}
      <figure className="pulse-chart" style={{ "--slots": PULSE_LIMIT } as CSSProperties}>
        <div className="pulse-plot">
          {items.length ? (
            <>
              <div className="chart-grid" aria-hidden="true">
                {ticks.slice(1).map((tick) => (
                  <span key={tick} style={{ bottom: pct(tick, scale) }}>
                    <em>{msTick(tick, ticks)}</em>
                  </span>
                ))}
              </div>
              {typical !== null ? (
                <span className="pulse-median" style={{ bottom: pct(typical, scale) }} aria-hidden="true" />
              ) : null}
              <ol className="pulse-bars" aria-hidden="true">
                {items.map((item, index) => (
                  <Tooltip
                    key={`${item.at}-${index}`}
                    placement="top"
                    mouseEnterDelay={0.05}
                    title={
                      <span className="timing-tip">
                        <strong>{item.duration_ms === null ? "耗时未记录" : secondsText(item.duration_ms)}</strong>
                        <span>
                          {item.hit ? "命中余票" : statusLabels[item.status] ?? "未取得结果"}
                          {item.date ? ` · 查询 ${shortDate(item.date)}` : ""}
                        </span>
                        <small>北京时间 {clock(item.at)}</small>
                      </span>
                    }
                  >
                    <li className={"pulse-slot " + pulseKind(item)}>
                      <i
                        className={"pulse-bar" + (item.duration_ms === null ? " unknown" : "")}
                        style={item.duration_ms === null ? undefined : { height: pct(item.duration_ms, scale) }}
                      />
                    </li>
                  </Tooltip>
                ))}
              </ol>
            </>
          ) : (
            <div className="chart-empty">
              {failed ? (
                <span>查询记录暂时无法读取</span>
              ) : !pulse ? (
                <span>正在读取查询记录…</span>
              ) : status.monitoring ? (
                <span>等待第一次查询完成</span>
              ) : (
                <>
                  <strong>还没有查询记录</strong>
                  <span>启动监控后，这里实时显示每次查询的耗时与结果。</span>
                  <Button size="small" onClick={() => navigate("购票监控")}>
                    前往购票监控
                  </Button>
                </>
              )}
            </div>
          )}
        </div>
        {items.length ? (
          <div className="pulse-axis" aria-hidden="true">
            <span>{clock(items[0].at, { hour: "2-digit", minute: "2-digit" })}</span>
            {items.length >= 16 && lastAt !== undefined ? (
              <span style={{ gridColumn: `${items.length - 7} / span 8` }}>
                {clock(lastAt, { hour: "2-digit", minute: "2-digit" })}
              </span>
            ) : null}
          </div>
        ) : null}
        <table className="sr-only">
          <caption>最近 {items.length} 次查询</caption>
          <thead>
            <tr>
              <th scope="col">北京时间</th>
              <th scope="col">查询日期</th>
              <th scope="col">耗时</th>
              <th scope="col">结果</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item, index) => (
              <tr key={`${item.at}-${index}`}>
                <td>{clock(item.at)}</td>
                <td>{item.date || "未记录"}</td>
                <td>{item.duration_ms === null ? "未记录" : secondsText(item.duration_ms)}</td>
                <td>{item.hit ? "命中余票" : statusLabels[item.status] ?? "未取得结果"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </figure>
      <div className="chart-foot">
        <div className="chart-legend" aria-hidden="true">
          <span>
            <i className="chart-key ok" />
            有结果
          </span>
          <span>
            <i className="chart-key hit" />
            命中余票
          </span>
          <span>
            <i className="chart-key miss" />
            未取得结果
          </span>
          <span>
            <i className="chart-key median" />
            中位耗时
          </span>
        </div>
      </div>
    </section>
  );
}

const outcomes = ["success", "pending", "running", "ended"] as const;
type Outcome = (typeof outcomes)[number];
const outcomeLabels: Record<Outcome, string> = { success: "成功", pending: "待处理", running: "进行中", ended: "已结束" };

function runOutcome(conclusion: string): Outcome {
  const tone = conclusionTone(conclusion);
  return tone === "go" ? "success" : tone === "wait" ? "pending" : tone === "info" ? "running" : "ended";
}

function useRunHistory(monitoring: boolean) {
  const [runs, setRuns] = useState<RunReviewSummary[] | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let alive = true;
    const since = Date.now() / 1000 - (HISTORY_DAYS + 1) * 86_400;
    void (async () => {
      const items: RunReviewSummary[] = [];
      let cursor: string | null = null;
      // Pages are newest first; stop once a page reaches past the window.
      for (let page = 0; page < 4; page += 1) {
        const result: { items: RunReviewSummary[]; next_cursor: string | null } = await railwatchApi.command(
          "runReviews",
          { limit: 50, cursor },
        );
        if (!result || !Array.isArray(result.items)) throw new Error("Invalid run review response");
        items.push(...result.items);
        cursor = result.next_cursor;
        if (!cursor || result.items.some((item) => item.started_at < since)) break;
      }
      if (alive) {
        setRuns(items);
        setFailed(false);
      }
    })().catch(() => {
      if (alive) setFailed(true);
    });
    return () => {
      alive = false;
    };
  }, [monitoring]);
  return { runs, failed };
}

export function RunHistoryCard({ monitoring, now }: { monitoring: boolean; now: number }) {
  const navigate = useRailWatchStore((state) => state.setActivePage);
  const { runs, failed } = useRunHistory(monitoring);
  const days = Array.from({ length: HISTORY_DAYS }, (_, index) =>
    isoDaysFromToday(index - HISTORY_DAYS + 1, new Date(now)),
  );
  const buckets = new Map(days.map((day) => [day, { success: 0, pending: 0, running: 0, ended: 0 }]));
  for (const run of runs ?? []) {
    const bucket = buckets.get(todayIso(new Date(run.started_at * 1000)));
    if (bucket) bucket[runOutcome(run.conclusion)] += 1;
  }
  const totals = days.map((day) => outcomes.reduce((sum, outcome) => sum + buckets.get(day)![outcome], 0));
  const total = totals.reduce((sum, value) => sum + value, 0);
  const successes = days.reduce((sum, day) => sum + buckets.get(day)!.success, 0);
  const top = Math.max(2, Math.ceil(Math.max(0, ...totals) / 2) * 2);
  return (
    <section className="chart-card history-card" aria-label="近 14 天运行">
      <div className="section-heading">
        <h2>
          <CalendarRange size={15} aria-hidden="true" /> 近 14 天运行
          <Hint text="按运行开始的日期统计每次监控的结论。成功含购票成功、候补已生效和已命中；待处理为待支付或待核对。" />
        </h2>
        <Button type="link" size="small" onClick={() => navigate("运行复盘")}>
          运行复盘 <ArrowRight size={13} aria-hidden="true" />
        </Button>
      </div>
      {total ? <dl className="chart-kpis">
        <div>
          <dt>运行次数</dt>
          <dd>{total}</dd>
        </div>
        <div className={successes ? "is-hit" : undefined}>
          <dt>成功</dt>
          <dd>{successes}</dd>
        </div>
      </dl> : null}
      <figure className="history-chart" style={{ "--days": HISTORY_DAYS } as CSSProperties}>
        <div className="history-plot">
          <div className="chart-grid" aria-hidden="true">
            {[top / 2, top].map((tick) => (
              <span key={tick} style={{ bottom: pct(tick, top) }}>
                <em>{tick}</em>
              </span>
            ))}
          </div>
          <ol className="history-bars" aria-hidden="true">
            {days.map((day, index) => {
              const bucket = buckets.get(day)!;
              const present = outcomes.filter((outcome) => bucket[outcome]);
              return (
                <Tooltip
                  key={day}
                  placement="top"
                  mouseEnterDelay={0.05}
                  title={
                    <span className="timing-tip">
                      <strong>{totals[index] ? `${totals[index]} 次运行` : "没有运行"}</strong>
                      <span>{index === HISTORY_DAYS - 1 ? "今天" : shortDate(day)}</span>
                      {present.length ? (
                        <small>{present.map((outcome) => `${outcomeLabels[outcome]} ${bucket[outcome]}`).join(" · ")}</small>
                      ) : null}
                    </span>
                  }
                >
                  <li className="history-slot">
                    {totals[index] ? (
                      <span className="history-stack" style={{ height: pct(totals[index], top) }}>
                        {present.map((outcome) => (
                          <i key={outcome} className={"history-seg " + outcome} style={{ flexGrow: bucket[outcome] }} />
                        ))}
                      </span>
                    ) : null}
                  </li>
                </Tooltip>
              );
            })}
          </ol>
          {failed || !runs || !total ? (
            <div className="chart-empty overlay">
              <span>{failed ? "运行记录暂时无法读取" : !runs ? "正在读取运行记录…" : "近 14 天没有运行记录"}</span>
            </div>
          ) : null}
        </div>
        <div className="history-axis" aria-hidden="true">
          <span>{shortDate(days[0])}</span>
          <span>今天</span>
        </div>
        <table className="sr-only">
          <caption>近 14 天每日运行结论</caption>
          <thead>
            <tr>
              <th scope="col">日期</th>
              {outcomes.map((outcome) => (
                <th scope="col" key={outcome}>
                  {outcomeLabels[outcome]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {days.map((day) => (
              <tr key={day}>
                <th scope="row">{day}</th>
                {outcomes.map((outcome) => (
                  <td key={outcome}>{buckets.get(day)![outcome]}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </figure>
      <div className="chart-foot">
        <div className="chart-legend" aria-hidden="true">
          {outcomes.map((outcome) => (
            <span key={outcome}>
              <i className={"chart-key " + outcome} />
              {outcomeLabels[outcome]}
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}
