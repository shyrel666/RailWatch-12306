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
      <Button onClick={() => setDetail(null)}>关闭复盘</Button></article> : null}
    </div> : null}
  </section>;
}
