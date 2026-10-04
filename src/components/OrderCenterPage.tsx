import { RunReviews } from "./RunReviews";
import { useEffect, useState } from "react";
import { Button, Select } from "antd";
import { RefreshCw } from "lucide-react";
import type { OrderHistoryDetail, OrderHistoryPage, OrderHistorySummary } from "../types";
import { useRailWatchStore } from "../store/useRailWatchStore";
import type { CommandRunner } from "./componentTypes";

const statusLabels: Record<string, string> = {
  submitting: "正在提交", pending_payment: "待支付", active: "候补已生效",
  fulfilled: "购票成功", unknown: "结果待核对", verification: "需要核验",
  dismissed: "本地核对已结束", cancelled: "官方已取消", expired: "已过期",
  failed: "候补兑现失败", sold_out: "无票", not_submitted: "未提交",
};

function time(value: number | null) {
  return value === null ? "未记录" : new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai",
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" })
    .format(new Date(value * 1000));
}

function officialSummary(item: OrderHistorySummary) {
  if (!item.official_status) return "尚无匹配的官方状态证据";
  if (item.official_status === "active") return item.observing
    ? "候补已生效；正在持续核对兑现状态"
    : "候补已生效；当前未持续核对，可点击继续核对";
  return `${statusLabels[item.official_status] ?? item.official_status} · 核对时间：${time(item.official_verified_at)}`;
}

export function OrderCenterPage({ runCommand, busy }: { runCommand: CommandRunner; busy: string | null }) {
  const [page, setPage] = useState<OrderHistoryPage>({ items: [], next_cursor: null });
  const [cursor, setCursor] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  const [detail, setDetail] = useState<OrderHistoryDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const activity = useRailWatchStore(state => state.status.activity);
  const monitoring = useRailWatchStore(state => state.status.monitoring);
  const orderUpdated = useRailWatchStore(state => state.status.order?.updated_at);

  useEffect(() => {
    let current = true;
    let inFlight = false;
    setLoading(true);
    const read = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const result = await runCommand<OrderHistoryPage>("orderHistory", { limit: 20, cursor, status: statusFilter });
        if (current && result) setPage(result);
      } finally {
        inFlight = false;
        if (current) setLoading(false);
      }
    };
    void read();
    const timer = monitoring ? window.setInterval(() => void read(), 5000) : null;
    return () => { current = false; if (timer !== null) window.clearInterval(timer); };
  }, [runCommand, cursor, statusFilter, orderUpdated, monitoring]);

  const showDetail = async (intentId: string) => {
    const result = await runCommand<OrderHistoryDetail>("orderDetail", { intent_id: intentId });
    if (result) setDetail(result);
  };
  const refresh = () => { setCursor(null); setDetail(null); void runCommand<OrderHistoryPage>("orderHistory", {
    limit: 20, cursor: null, status: statusFilter,
  }).then(result => { if (result) setPage(result); }); };
  const canReview = (item: OrderHistorySummary) => item.recovery_required && !monitoring && activity?.state !== "busy";

  return <div className="order-center">
    <header className="order-center-head"><div><span className="eyebrow">订单中心</span>
      <h2>本地订单历史</h2><p>官方订单状态以匹配页面证据为准；历史查看不占用浏览器。</p></div>
      <div className="order-center-actions">
        <Select aria-label="按状态筛选" value={statusFilter ?? "all"} onChange={value => { setStatusFilter(value === "all" ? null : value); setCursor(null); }}
          options={[{ value: "all", label: "全部状态" }, ...Object.entries(statusLabels).map(([value, label]) => ({ value, label }))]} />
        <Button icon={<RefreshCw size={14} />} onClick={refresh}>刷新</Button>
      </div>
    </header>
    {loading ? <p role="status">正在读取订单历史…</p> : page.items.length === 0 ? <p>暂无符合条件的订单记录。</p> :
      <div className="order-history-list">{page.items.map(item => <article key={item.intent_id} className="order-history-item">
        <header><strong>{item.date} · {item.train_code} · {item.from_station} → {item.to_station}</strong>
          <span>{statusLabels[item.status] ?? item.status}</span></header>
        <p>{item.kind === "alternate" ? "候补" : "普通购票"} · {item.seat} · 官方单号：{item.order_id ?? "未取得"}</p>
        {item.choices && item.choices.length > 1 ? <details className="order-choice-list">
          <summary>已保存的候补组合（{item.choices.length}个）</summary>
          <ol>{item.choices.map(choice => <li key={[choice.date, choice.train_code, choice.from_station, choice.to_station, choice.seat].join(":")}>
            {choice.date} · {choice.train_code} · {choice.from_station} → {choice.to_station} · {choice.seat}
          </li>)}</ol>
        </details> : null}
        <p>最近页面核对：{time(item.last_checked_at)} · {item.observing ? "本地观察中" : "当前未观察"}</p>
        {item.observing && item.next_check_at != null ? <p>下次核对：{time(item.next_check_at)}{item.check_failures ? " · 暂未取得新证据，已放慢核对，保留最后确认状态" : ""}</p> : null}
        {item.last_check_status ? <p>最近核对结果：{item.last_check_status === "error" ? "页面读取失败" : statusLabels[item.last_check_status] ?? item.last_check_status}</p> : null}
        <p>最后确认的官方状态：{officialSummary(item)}</p>
        <div className="order-center-actions"><Button onClick={() => void showDetail(item.intent_id)}>查看时间线</Button>
          {item.observing ? <Button loading={busy === "stopMonitor"} onClick={() => void runCommand("stopMonitor").then(refresh)}>停止本地核对</Button> : null}
          {canReview(item) ? <Button loading={busy === "continueOrder"} onClick={() => void runCommand("continueOrder", { intent_id: item.intent_id }).then(refresh)}>继续核对</Button> : null}
        </div>
      </article>)}</div>}
    {page.next_cursor ? <Button onClick={() => { setCursor(page.next_cursor); setDetail(null); }}>下一页</Button> : null}
    {detail ? <section className="order-detail" aria-label="订单时间线">
      <header><h3>{detail.summary.train_code} · {detail.summary.date}</h3><Button onClick={() => setDetail(null)}>关闭详情</Button></header>
      <p>本地结果：{statusLabels[detail.summary.status] ?? detail.summary.status}；{officialSummary(detail.summary)}</p>
      {detail.summary.status === "dismissed" ? <p>已结束本地核对；此操作不等于取消官方订单。</p> : null}
      {!detail.history_complete ? <p role="status">历史事件不完整；缺失的时间不会推测补齐。</p> : null}
      {detail.events_truncated ? <p role="status">仅显示最近 500 条事件，更早记录仍保存在本地。</p> : null}
      <ol>{detail.events.map(event => <li key={event.sequence}>
        <time>{time(event.at)}</time> · {event.scope === "official" ? "官方页面证据" : "本地处理"} · {event.message}
      </li>)}</ol>
      {canReview(detail.summary) ? <div className="order-center-actions">
        <Button loading={busy === "continueOrder"} onClick={() => void runCommand("continueOrder", { intent_id: detail.summary.intent_id }).then(refresh)}>继续处理／核对</Button>
        {["unknown", "verification"].includes(detail.summary.status) ? <Button loading={busy === "dismissOrder"}
          onClick={() => void runCommand("dismissOrder", { intent_id: detail.summary.intent_id }).then(refresh)}>
          结束本地核对（不取消官方订单）</Button> : null}
      </div> : null}
    </section> : null}
    <RunReviews />
  </div>;
}
