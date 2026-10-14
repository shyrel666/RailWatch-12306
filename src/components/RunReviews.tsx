import { useEffect, useRef, useState } from "react";
import { Button } from "antd";
import { History, RefreshCw } from "lucide-react";
import type { RunReviewDetail, RunReviewSummary } from "../lib/rehearsal";
import { millis, seconds, span } from "../lib/chartScale";
import { railwatchApi } from "../lib/railwatchApi";
import { conclusionTone } from "../lib/runConclusion";
import { useRailWatchStore } from "../store/useRailWatchStore";
import { TimelineWaterfall } from "./TimelineWaterfall";
import { TimingRangeChart } from "./TimingRangeChart";

type Page = { items: RunReviewSummary[]; next_cursor: string | null };

const shanghai = { timeZone: "Asia/Shanghai", hourCycle: "h23" } as const;
const clock = (at: number | undefined, options: Intl.DateTimeFormatOptions) => typeof at === "number" && Number.isFinite(at)
  ? new Intl.DateTimeFormat("zh-CN", { ...shanghai, month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", ...options })
    .format(new Date(at * 1000)) : "时间未记录";

function route(trip?: RunReviewSummary["trip"]) {
  return trip?.from_station || trip?.to_station
    ? `${trip.from_station || "未记录出发站"} → ${trip.to_station || "未记录到达站"}` : "路线未记录";
}

function day(value?: string) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value ?? "");
  if (!match) return null;
  const weekday = "日一二三四五六"[new Date(Date.UTC(+match[1], +match[2] - 1, +match[3])).getUTCDay()];
  return `${Number(match[2])}月${Number(match[3])}日 周${weekday}`;
}

function Conclusion({ value }: { value: string }) {
  const tone = conclusionTone(value);
  return <span className={"rv-conclusion " + tone}><i className={"lamp " + tone + (tone === "info" ? " live" : "")} aria-hidden="true" />{value}</span>;
}

function Detail({ detail, busy }: { detail: RunReviewDetail; busy: boolean }) {
  const segments = detail.segments ?? [];
  const known = segments.filter(s => s.duration_ms !== null);
  const total = known.reduce((sum, s) => sum + (s.duration_ms ?? 0), 0);
  const slowest = known.find(s => s.label === detail.slowest);
  const margin = detail.preparation_margin_ms ?? null;
  const timed = detail.target_at != null;
  const timings = detail.query_timings;
  const firstValid = detail.first_valid_query ?? null;
  const orders = detail.order_timings ?? [];
  const travel = day(detail.trip?.date);
  return <article className="rv-detail" aria-label="复盘详情" aria-busy={busy || undefined}>
    <header className="rv-detail-head">
      <div>
        <h3>{route(detail.trip)}</h3>
        <p>{timed ? `定时任务 · 起售 ${clock(detail.target_at!, { second: "2-digit" })}` : `即时任务 · 开始于 ${clock(detail.started_at, { second: "2-digit" })}`}
          {travel ? ` · ${travel}出发` : ""}</p>
      </div>
      <Conclusion value={detail.conclusion} />
    </header>
    <dl className="rv-stats">
      <div className={margin !== null && margin < 10_000 ? "is-warn" : undefined}>
        <dt>准备余量</dt><dd>{margin === null ? "未记录" : span(margin)}</dd>
        <dd className="rv-stat-note">{margin === null ? timed ? "未记录准备完成时间" : "即时任务无起售时刻"
          : margin < 10_000 ? "不足 10 秒，建议提前启动" : "准备完成到起售的时间"}</dd>
      </div>
      <div><dt>查询中位数</dt><dd>{detail.query_median_ms == null ? "未记录" : seconds(detail.query_median_ms)}</dd>
        <dd className="rv-stat-note">唤醒后前五轮查询</dd></div>
      <div><dt>已知阶段合计</dt><dd>{seconds(total)}</dd>
        <dd className="rv-stat-note">{known.length}/{segments.length} 个阶段有记录</dd></div>
      <div><dt>最慢阶段</dt><dd>{detail.slowest ?? "阶段未记录"}</dd>
        <dd className="rv-stat-note">{slowest && total ? `${seconds(slowest.duration_ms!)} · 占已知 ${Math.round(slowest.duration_ms! / total * 100)}%` : "—"}</dd></div>
    </dl>
    <section className="rv-section" aria-label="阶段时间线">
      <h4>阶段时间线{timed ? <small>以起售时刻为 0</small> : <small>即时任务按阶段先后排列</small>}</h4>
      {timed ? <p className="rv-section-note">{firstValid
        ? `首个有效查询：起售后 ${seconds(firstValid.offset_ms)}，第 ${firstValid.round} 轮取得；此前 ${firstValid.presale_rounds} 轮仍显示未开售，其中快速重查 ${firstValid.sale_retries} 次。`
        : "首个有效查询未记录：起售后的查询记录不完整，或尚未取得已开售的有效结果。"}</p> : null}
      <TimelineWaterfall segments={segments} prediction={detail.prediction ?? []} origin={timed ? "距起售" : undefined} />
    </section>
    {orders.length ? <section className="rv-section" aria-label="下单分步耗时">
      <h4>下单分步耗时</h4>
      <p className="rv-section-note">每组从进入下单流程计时，细分上方已有阶段，不重复计入总耗时。中断时仅显示已观察的部分；包含页面和本机操作的等待。</p>
      {orders.map((group, index) => <div className="rv-subchart" key={index}>
        <h5>{group.kind === "alternate" ? "候补订单" : "普通订单"} · 第 {index + 1} 段流程</h5>
        <TimelineWaterfall segments={group.segments} origin="进入下单后" label={`第 ${index + 1} 段下单流程耗时`} />
      </div>)}
    </section> : <p className="rv-missing">本次没有下单分步记录；历史任务无法补算各步骤耗时。</p>}
    {timings?.recorded_queries ? <section className="rv-section" aria-label="查询分阶段统计">
      <h4>查询分阶段统计</h4>
      <p className="rv-section-note">最近最多{timings.window_limit}轮记录中，{timings.valid_queries}轮取得有效结果，共{timings.recorded_queries}轮有记录。
        耗时包含本机操作与页面等待；未记录的阶段不补算，中断步骤可能只记录部分。P95表示95%的样本不超过此值，少量样本仅供参考。
        {timings.resettle?.attempts ? `结果判定后页面又变化${timings.resettle.attempts}次，其中${timings.resettle.accepted}次重新稳定后继续使用本轮结果，其余整页重载。` : ""}</p>
      <div className="rv-subchart">
        <h5>有效查询各阶段耗时</h5>
        <TimingRangeChart rows={timings.phases} format={millis} label="有效查询各阶段耗时" />
      </div>
      <div className="rv-subchart">
        <h5>同一日期两次查询的实际间隔<small>含失败查询</small></h5>
        {timings.date_revisits.length ? <TimingRangeChart format={seconds} label="同一日期两次查询的实际间隔"
          rows={timings.date_revisits.map(item => ({ ...item, id: item.date, label: day(item.date) ?? item.date }))} />
          : <p className="rv-missing">尚无同一日期的重复查询记录。</p>}
      </div>
      <details className="rv-data">
        <summary>查看数据表</summary>
        <div className="query-timing-table-wrap"><table className="query-timing-table">
          <caption>有效查询各阶段耗时</caption>
          <thead><tr><th>阶段</th><th>样本</th><th>中位数</th><th>P95</th></tr></thead>
          <tbody>{timings.phases.map(phase => <tr key={phase.id}>
            <th scope="row">{phase.label}</th><td>{phase.samples}</td><td>{millis(phase.median_ms)}</td><td>{millis(phase.p95_ms)}</td>
          </tr>)}</tbody>
        </table></div>
        {timings.date_revisits.length ? <div className="query-timing-table-wrap"><table className="query-timing-table">
          <caption>同一日期两次查询的实际间隔（含失败查询）</caption>
          <thead><tr><th>日期</th><th>样本</th><th>中位数</th><th>P95</th></tr></thead>
          <tbody>{timings.date_revisits.map(item => <tr key={item.date}>
            <th scope="row">{item.date}</th><td>{item.samples}</td><td>{seconds(item.median_ms)}</td><td>{seconds(item.p95_ms)}</td>
          </tr>)}</tbody>
        </table></div> : null}
      </details>
    </section> : <p className="rv-missing">本次未记录查询分阶段耗时。</p>}
    {detail.note ? <p className="rv-note">{detail.note}</p> : null}
  </article>;
}

export function RunReviews() {
  const [page, setPage] = useState<Page | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<RunReviewDetail | null>(null);
  const [loadingRun, setLoadingRun] = useState<string | null>(null);
  const [error, setError] = useState("");
  const autoOpened = useRef(false);
  // Responses can arrive out of order; only the latest requested run may fill the detail.
  const requestedRun = useRef<string | null>(null);
  const monitoring = useRailWatchStore(s => s.status.monitoring);
  const navigate = useRailWatchStore(s => s.setActivePage);
  const read = async (next: string | null = null) => {
    try { setPage(await railwatchApi.command<Page>("runReviews", { limit: 20, cursor: next })); setCursor(next); setError(""); }
    catch { setError("运行复盘暂时无法读取"); }
  };
  useEffect(() => { let current = true;
    void railwatchApi.command<Page>("runReviews", { limit: 20 }).then(value => { if (current) { setPage(value); setCursor(null); } })
      .catch(() => { if (current) setError("运行复盘暂时无法读取"); });
    return () => { current = false; };
  }, [monitoring]);
  const open = async (runId: string) => {
    requestedRun.current = runId;
    setSelected(runId);
    setLoadingRun(runId);
    try {
      const value = await railwatchApi.command<RunReviewDetail>("runReview", { run_id: runId });
      if (requestedRun.current === runId) { setDetail(value); setError(""); }
    } catch {
      if (requestedRun.current === runId) setError("该任务复盘暂时无法读取");
    } finally { setLoadingRun(current => current === runId ? null : current); }
  };
  // The newest run opens right away, so the charts are the first thing on the page.
  useEffect(() => {
    if (autoOpened.current || !page?.items[0]) return;
    autoOpened.current = true;
    void open(page.items[0].run_id);
  }, [page]);
  const items = page?.items ?? [];
  return <div className="run-review-page" id="run-reviews">
    <header className="rv-toolbar">
      <p className="rv-summary">
        {items.length ? <span><strong>{items.length}</strong> 次运行{cursor ? "（更早）" : ""}</span> : null}
      </p>
      <Button icon={<RefreshCw size={14} aria-hidden="true" />} onClick={() => { void read(); if (selected) void open(selected); }}>刷新复盘</Button>
    </header>
    {error ? <p className="rv-error" role="status">{error}</p> : null}
    {!page ? <p className="rv-detail rv-placeholder" role="status">正在读取运行记录…</p> : !items.length ? <div className="rv-empty">
      <span className="rv-empty-icon"><History size={22} aria-hidden="true" /></span>
      <strong>暂无任务复盘记录</strong>
      <span>运行一次即时或定时监控后，可在这里查看各阶段耗时、下单分步和查询统计。</span>
      <Button size="small" onClick={() => navigate("购票监控")}>前往购票监控</Button>
    </div> : <div className="rv-layout">
      <nav className="rv-list" aria-label="任务列表">
        <ol className="rv-runs">{items.map(item => <li key={item.run_id}>
          <button type="button" className={item.run_id === selected ? "rv-run is-selected" : "rv-run"}
            aria-label="查看复盘" aria-pressed={item.run_id === selected} onClick={() => void open(item.run_id)}>
            <Conclusion value={item.conclusion} />
            <time>{clock(item.target_at ?? item.started_at, {})}</time>
            <span className="rv-run-trip">{route(item.trip)} · {item.target_at != null ? "定时" : "即时"}</span>
          </button>
        </li>)}</ol>
        {cursor || page.next_cursor ? <div className="rv-pager">
          {cursor ? <Button size="small" onClick={() => void read()}>回到最新</Button> : null}
          {page.next_cursor ? <Button size="small" onClick={() => void read(page.next_cursor)}>下一页复盘</Button> : null}
        </div> : null}
      </nav>
      {detail ? <Detail detail={detail} busy={loadingRun !== null} />
        : <p className="rv-detail rv-placeholder" role="status">{loadingRun ? "正在读取复盘…" : "选择一次任务查看耗时图表。"}</p>}
    </div>}
  </div>;
}
