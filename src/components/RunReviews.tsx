import { useEffect, useState } from "react";
import { Button } from "antd";
import { ChevronDown, ChevronRight, History, RefreshCw } from "lucide-react";
import type { RunReviewDetail, RunReviewSummary } from "../lib/rehearsal";
import { railwatchApi } from "../lib/railwatchApi";
import { useRailWatchStore } from "../store/useRailWatchStore";
import { TimelineWaterfall } from "./TimelineWaterfall";

type Page = { items: RunReviewSummary[]; next_cursor: string | null };
export function RunReviews() {
  const [page, setPage] = useState<Page>({ items: [], next_cursor: null });
  const [detail, setDetail] = useState<RunReviewDetail | null>(null);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState(false);
  const monitoring = useRailWatchStore(s => s.status.monitoring);
  const pageSection = useRailWatchStore(s => s.pageSection);
  useEffect(() => { if (pageSection === "order-run-reviews") setExpanded(true); }, [pageSection]);
  const read = async (cursor?: string | null) => {
    try { setPage(await railwatchApi.command<Page>("runReviews", { limit: 20, cursor })); setError(""); }
    catch { setError("运行复盘暂时无法读取"); }
  };
  useEffect(() => { let current = true;
    void railwatchApi.command<Page>("runReviews", { limit: 20 }).then(value => { if (current) setPage(value); })
      .catch(() => { if (current) setError("运行复盘暂时无法读取"); });
    return () => { current = false; };
  }, [monitoring]);
  const open = async (runId: string) => {
    try { setDetail(await railwatchApi.command<RunReviewDetail>("runReview", { run_id: runId })); setError(""); }
    catch { setError("该任务复盘暂时无法读取"); }
  };
  return <section id="order-run-reviews" tabIndex={-1} className="rehearsal-panel run-reviews" aria-label="运行复盘">
    <h2 className="run-reviews-heading"><button type="button" className="run-reviews-toggle" aria-expanded={expanded}
      aria-controls="run-reviews-content" onClick={() => setExpanded(value => !value)}>
      {expanded ? <ChevronDown size={16} aria-hidden="true" /> : <ChevronRight size={16} aria-hidden="true" />}
      <span>运行复盘</span><small>查看任务耗时与结果</small>
    </button></h2>
    {expanded ? <div id="run-reviews-content">
    <div className="run-reviews-toolbar"><p>记录即时与定时监控的执行阶段；缺少记录时不会推断为未命中或失败。</p><Button icon={<RefreshCw size={14} aria-hidden="true" />} onClick={() => void read()}>刷新复盘</Button></div>
    {error ? <p role="status">{error}</p> : null}
    {!page.items.length ? <div className="run-reviews-empty"><History size={24} aria-hidden="true" /><p>暂无任务复盘记录。</p><small>运行监控任务后，可在这里查看执行过程与结果。</small></div> : page.items.map(item => <div className="run-review-item" key={item.run_id}>
      <span>{new Date((item.target_at ?? item.started_at) * 1000).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" })} · {item.target_at != null ? "定时任务" : "即时任务"} · {item.trip?.from_station || item.trip?.to_station ? `${item.trip.from_station || "未记录出发站"} → ${item.trip.to_station || "未记录到达站"}` : "路线未记录"} · {item.conclusion}</span>
      <Button onClick={() => void open(item.run_id)}>查看复盘</Button></div>)}
    {page.next_cursor ? <Button onClick={() => void read(page.next_cursor)}>下一页复盘</Button> : null}
    {detail ? <article className="run-review-detail" aria-label="复盘详情"><h3>{detail.conclusion} · {detail.slowest ? `最慢阶段：${detail.slowest}` : "阶段未记录"}</h3>
      <p className={detail.preparation_margin_ms !== null && detail.preparation_margin_ms < 10_000 ? "rehearsal-warning" : ""}>准备余量：{detail.preparation_margin_ms === null ? "未记录" : `${(detail.preparation_margin_ms / 1000).toFixed(2)} 秒`}</p>
      <p>唤醒后前五轮查询中位数：{detail.query_median_ms == null ? "未记录" : `${(detail.query_median_ms / 1000).toFixed(2)} 秒`}</p>
      <TimelineWaterfall segments={detail.segments} prediction={detail.prediction} /><p>{detail.note}</p>
      {detail.query_timings?.recorded_queries ? <section aria-label="查询分阶段统计">
        <h4>查询分阶段统计</h4>
        <p>最近最多{detail.query_timings.window_limit}轮记录中，{detail.query_timings.valid_queries}轮取得有效结果，共{detail.query_timings.recorded_queries}轮有记录。
          耗时包含本机操作与页面等待；未记录的阶段不补算，中断步骤可能只记录部分。P95表示95%的样本不超过此值，少量样本仅供参考。</p>
        <div className="query-timing-table-wrap"><table className="query-timing-table">
          <caption>有效查询各阶段耗时</caption>
          <thead><tr><th>阶段</th><th>样本</th><th>中位数</th><th>P95</th></tr></thead>
          <tbody>{detail.query_timings.phases.map(phase => <tr key={phase.id}>
            <th scope="row">{phase.label}</th><td>{phase.samples}</td>
            <td>{phase.median_ms.toFixed(1)} ms</td><td>{phase.p95_ms.toFixed(1)} ms</td>
          </tr>)}</tbody>
        </table></div>
        {detail.query_timings.date_revisits.length ? <div className="query-timing-table-wrap"><table className="query-timing-table">
          <caption>同一日期两次查询的实际间隔（含失败查询）</caption>
          <thead><tr><th>日期</th><th>样本</th><th>中位数</th><th>P95</th></tr></thead>
          <tbody>{detail.query_timings.date_revisits.map(item => <tr key={item.date}>
            <th scope="row">{item.date}</th><td>{item.samples}</td>
            <td>{(item.median_ms / 1000).toFixed(2)} 秒</td><td>{(item.p95_ms / 1000).toFixed(2)} 秒</td>
          </tr>)}</tbody>
        </table></div> : <p>尚无同一日期的重复查询记录。</p>}
      </section> : <p>本次未记录查询分阶段耗时。</p>}
      {detail.order_timings?.length ? <section aria-label="下单分步耗时">
        <h4>下单分步耗时</h4>
        <p>每组从进入下单流程计时，细分上方已有阶段，不重复计入总耗时。中断时仅显示已观察的部分；包含页面和本机操作的等待。</p>
        {detail.order_timings.map((group, index) => <div key={index}>
          <h5>{group.kind === "alternate" ? "候补订单" : "普通订单"} · 第 {index + 1} 段流程</h5>
          <TimelineWaterfall segments={group.segments} />
        </div>)}
      </section> : <p>本次没有下单分步记录；历史任务无法补算各步骤耗时。</p>}
      <Button onClick={() => setDetail(null)}>关闭复盘</Button></article> : null}
    </div> : null}
  </section>;
}
