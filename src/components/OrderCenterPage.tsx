import { AlternateReview } from "./AlternateReview";
import { canonicalDeadline } from "../lib/alternateOptions";
import { useEffect, useState, type ReactNode } from "react";
import { Button, Drawer, Select } from "antd";
import { ArrowRight, ChevronRight, History, Info, ListFilter, ReceiptText, RefreshCw, SearchX } from "lucide-react";
import type { AlternateChoice, OrderHistoryDetail, OrderHistoryPage, OrderHistorySummary, OrderTimelineEvent } from "../types";
import { getTripDateStatus, useBeijingToday } from "../lib/tripDate";
import { useRailWatchStore } from "../store/useRailWatchStore";
import type { CommandRunner } from "./componentTypes";

type Tone = "go" | "wait" | "stop" | "info" | "neutral";
type Group = "attention" | "active" | "ended";

const statusLabels: Record<string, string> = {
  submitting: "正在提交", pending_payment: "待支付", active: "候补已生效",
  fulfilled: "购票成功", unknown: "结果待核对", verification: "需要核验",
  dismissed: "本地核对已结束", cancelled: "官方已取消", expired: "已过期",
  failed: "候补兑现失败", sold_out: "无票", not_submitted: "未提交",
};

const statusTones: Record<string, Tone> = {
  fulfilled: "go", active: "go", pending_payment: "wait", unknown: "wait", verification: "wait",
  submitting: "info", failed: "stop", cancelled: "stop", expired: "stop", sold_out: "stop",
};

const finalOfficial = new Set(["fulfilled", "cancelled", "expired", "failed"]);
// Mirrors TERMINAL in railwatch_orders.py: nothing further happens locally.
const terminal = new Set(["sold_out", "not_submitted", "fulfilled", "cancelled", "expired", "failed", "dismissed"]);

const groups: { id: Group; title: string; tone: Tone }[] = [
  { id: "attention", title: "需要你处理", tone: "wait" },
  { id: "active", title: "进行中", tone: "go" },
  { id: "ended", title: "已结束", tone: "neutral" },
];

const filterOption = (value: string) => ({ value, label: statusLabels[value] });
const filterOptions = [
  { value: "all", label: "全部状态" },
  { label: "需要处理", title: "需要处理", options: ["pending_payment", "verification", "unknown"].map(filterOption) },
  { label: "进行中", title: "进行中", options: ["submitting", "active"].map(filterOption) },
  { label: "已结束", title: "已结束", options: ["fulfilled", "failed", "cancelled", "expired", "sold_out", "not_submitted", "dismissed"].map(filterOption) },
];

const pageKey = (cursor: string | null, status: string | null) => `${cursor ?? ""}|${status ?? ""}`;

const shanghai = { timeZone: "Asia/Shanghai" } as const;

function time(value: number | null) {
  return value === null ? "未记录" : new Intl.DateTimeFormat("zh-CN", { ...shanghai,
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" })
    .format(new Date(value * 1000));
}

function shortTime(value: number | null) {
  return value === null ? "未记录" : new Intl.DateTimeFormat("zh-CN", { ...shanghai,
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value * 1000));
}

function clockTime(value: number) {
  return new Intl.DateTimeFormat("zh-CN", { ...shanghai, hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" })
    .format(new Date(value * 1000));
}

function shanghaiDate(value: number) {
  return new Intl.DateTimeFormat("en-CA", { ...shanghai, year: "numeric", month: "2-digit", day: "2-digit" })
    .format(new Date(value * 1000));
}

function tripParts(value: string) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return null;
  const weekday = "日一二三四五六"[new Date(Date.UTC(+match[1], +match[2] - 1, +match[3])).getUTCDay()];
  return { day: `${Number(match[2])}月${Number(match[3])}日`, weekday: `周${weekday}` };
}

function tripDate(value: string) {
  const parts = tripParts(value);
  return parts ? `${parts.day} ${parts.weekday}` : value;
}

// An alternate order that waits for payment is waiting for its prepayment.
function statusLabel(status: string, kind?: OrderHistorySummary["kind"]) {
  if (status === "pending_payment" && kind === "alternate") return "候补待支付";
  return statusLabels[status] ?? status;
}

const kindLabel = (item: OrderHistorySummary) => item.kind === "alternate" ? "候补订单" : "普通订单";

function officialSummary(item: OrderHistorySummary, short = false) {
  if (!item.official_status) return "尚无匹配的官方状态证据";
  if (item.official_status === "active") return item.observing
    ? "候补已生效；正在持续核对兑现状态"
    : "候补已生效；当前未持续核对，可点击继续核对";
  return `${statusLabel(item.official_status, item.kind)} · 核对于 ${short ? shortTime(item.official_verified_at) : time(item.official_verified_at)}`;
}

// What the user still has to do in the official site, if anything. A final
// official status is newer evidence than an unresolved local result, and a
// dismissed record only keeps its last official observation, which may be stale.
function nextStep(item: OrderHistorySummary): string | null {
  if (item.status === "dismissed" || (item.official_status && finalOfficial.has(item.official_status))) return null;
  if (item.status === "pending_payment" || item.official_status === "pending_payment") return item.kind === "alternate"
    ? "请立即在 12306 官方页面完成预付款，支付后候补才生效" : "请尽快在 12306 官方页面完成支付";
  if (item.status === "verification") return "请在官方页面完成核验";
  if (item.status === "unknown") return "请在官方页面核对订单结果";
  return null;
}

function orderGroup(item: OrderHistorySummary): Group {
  if (nextStep(item)) return "attention";
  if (!item.observing && (terminal.has(item.status) || (item.official_status && finalOfficial.has(item.official_status)))) return "ended";
  return "active";
}

// Finished records show their newest evidence: a final official status outranks the local result.
function settledStatus(item: OrderHistorySummary) {
  return item.official_status && finalOfficial.has(item.official_status) ? item.official_status : item.status;
}

function checkResult(status: string) {
  return status === "error" ? "页面读取失败" : statusLabels[status] ?? status;
}

function StatusBadge({ status, kind }: { status: string; kind?: OrderHistorySummary["kind"] }) {
  return <span className={"order-status " + (statusTones[status] ?? "neutral")}>{statusLabel(status, kind)}</span>;
}

function Route({ item }: { item: OrderHistorySummary }) {
  return <div className="order-route">
    <span className="order-station" title={item.from_station}>{item.from_station}</span>
    <span className="order-track"><strong className="order-train">{item.train_code}</strong></span>
    <span className="sr-only">至</span>
    <span className="order-station" title={item.to_station}>{item.to_station}</span>
  </div>;
}

function ChoiceList({ choices }: { choices: AlternateChoice[] }) {
  return <details className="order-choice-list">
    <summary><ChevronRight size={14} aria-hidden="true" />已保存的候补组合（{choices.length}个）</summary>
    <ol>{choices.map(choice => <li key={[choice.date, choice.train_code, choice.from_station, choice.to_station, choice.seat].join(":")}>
      <span title={choice.date}>{tripDate(choice.date)}</span>
      <strong className="mono">{choice.train_code}</strong>
      <span>{choice.from_station} → {choice.to_station}</span>
      <span>{choice.seat}</span>
    </li>)}</ol>
  </details>;
}

function CheckFacts({ item }: { item: OrderHistorySummary }) {
  return <dl className="order-facts">
    <div><dt>最近核对</dt><dd>{shortTime(item.last_checked_at)} · {item.observing ? "本地观察中" : "当前未观察"}</dd></div>
    {item.observing && item.next_check_at != null ? <div><dt>下次核对</dt>
      <dd>{shortTime(item.next_check_at)}{item.check_failures ? " · 暂未取得新证据，已放慢核对" : ""}</dd></div> : null}
    {item.last_check_status ? <div><dt>核对结果</dt><dd>{checkResult(item.last_check_status)}</dd></div> : null}
  </dl>;
}

function departureNote(date: string, today: Date) {
  const days = getTripDateStatus(date, today).daysFromToday;
  if (days === null) return null;
  return days < 0 ? "已过出发日期" : days === 0 ? "今天出发" : days === 1 ? "明天出发" : `${days} 天后出发`;
}

function Departure({ date, today }: { date: string; today: Date }) {
  const parts = tripParts(date);
  const note = departureNote(date, today);
  return <div className="order-departure" title={date}>
    <strong>{parts?.day ?? date}</strong>
    {parts ? <span>{parts.weekday}{note ? ` · ${note}` : ""}</span> : null}
  </div>;
}

function OrderTicket({ item, group, actions, today }: { item: OrderHistorySummary; group: Group; actions: ReactNode; today: Date }) {
  const step = nextStep(item);
  const tone = group === "attention" ? "wait" : statusTones[item.status] ?? "neutral";
  return <article className={"order-history-item order-ticket is-" + group}
    aria-label={`${item.train_code} ${item.from_station}至${item.to_station}`}>
    <div className="order-ticket-main">
      <div className="order-ticket-head">
        <Route item={item} />
        <Departure date={item.date} today={today} />
      </div>
      <div className="order-meta">
        <span>{item.seat}</span>
        <span>{kindLabel(item)}</span>
        {item.order_id ? <span>单号 <span className="mono">{item.order_id}</span></span> : null}
      </div>
      {item.kind === "alternate" ? <AlternateReview review={item.review} deadline={item.deadline} windows={item.new_train_windows} /> : null}
      {item.choices && item.choices.length > 1 ? <ChoiceList choices={item.choices} /> : null}
      <CheckFacts item={item} />
    </div>
    <div className="order-ticket-stub">
      <strong className={"order-stub-status " + tone}>
        <i className={"lamp" + (item.observing ? " live" : "")} aria-hidden="true" />{statusLabel(item.status, item.kind)}
      </strong>
      <p className="order-official"><span>官方状态</span>{officialSummary(item, true)}</p>
      {step ? <p className="order-next-step"><ArrowRight size={14} aria-hidden="true" />{step}</p> : null}
      <div className="order-ticket-actions">{actions}</div>
    </div>
  </article>;
}

function OrderRow({ item, actions }: { item: OrderHistorySummary; actions: ReactNode }) {
  const status = settledStatus(item);
  const official = status === item.official_status;
  return <article className="order-history-item order-row" aria-label={`${item.train_code} ${item.from_station}至${item.to_station}`}>
    <strong className="order-train">{item.train_code}</strong>
    <span className="order-row-route" title={`${item.from_station} → ${item.to_station}`}>{item.from_station} → {item.to_station}</span>
    <span className="order-meta">
      <span className="order-date" title={item.date}>{tripDate(item.date)}</span>
      <span>{item.seat}</span>
      <span>{kindLabel(item)}</span>
      {item.order_id ? <span className="mono">{item.order_id}</span> : null}
    </span>
    <span className="order-row-status">
      <span className={"order-status-text " + (statusTones[status] ?? "neutral")}><i className="lamp" aria-hidden="true" />{statusLabel(status, item.kind)}</span>
      <small>{official ? `官方确认${item.official_verified_at === null ? "" : ` · ${shortTime(item.official_verified_at)}`}`
        : `本地记录 · ${shortTime(item.updated_at)}`}</small>
    </span>
    <div className="order-row-actions">{actions}</div>
  </article>;
}

// Newest first, grouped by Beijing calendar day.
function Timeline({ events }: { events: OrderTimelineEvent[] }) {
  const days: { day: string; events: OrderTimelineEvent[] }[] = [];
  for (const event of [...events].reverse()) {
    const day = shanghaiDate(event.at);
    if (days.at(-1)?.day !== day) days.push({ day, events: [] });
    days.at(-1)!.events.push(event);
  }
  return <div className="order-timeline">{days.map(({ day, events: items }) => <section key={day}>
    <h4>{tripDate(day)}</h4>
    <ol>{items.map(event => <li key={event.sequence} className={event.scope}>
      <time dateTime={new Date(event.at * 1000).toISOString()} title={time(event.at)}>{clockTime(event.at)}</time>
      <span className="order-timeline-scope">{event.scope === "official" ? "官方页面证据" : "本地处理"}</span>
      <p>{event.message}</p>
    </li>)}</ol>
  </section>)}</div>;
}

function Skeleton() {
  return <div className="order-history-list" aria-hidden="true">{[0, 1].map(key => <div key={key} className="order-ticket is-skeleton">
    <div className="order-ticket-main"><i style={{ width: "46%", height: 22 }} /><i style={{ width: "62%" }} /><i style={{ width: "34%" }} /></div>
    <div className="order-ticket-stub"><i style={{ width: "48%", height: 18 }} /><i style={{ width: "86%" }} /><i style={{ width: "64%" }} /></div>
  </div>)}</div>;
}

export function OrderCenterPage({ runCommand, busy }: { runCommand: CommandRunner; busy: string | null }) {
  const [page, setPage] = useState<OrderHistoryPage>({ items: [], next_cursor: null });
  const [cursor, setCursor] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  const [detail, setDetail] = useState<OrderHistoryDetail | null>(null);
  // Background refreshes keep the current list; only a new page or filter shows the placeholder.
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [replacementDeadline, setReplacementDeadline] = useState<string | undefined>();
  const activity = useRailWatchStore(state => state.status.activity);
  const monitoring = useRailWatchStore(state => state.status.monitoring);
  const orderUpdated = useRailWatchStore(state => state.status.order?.updated_at);
  const today = useBeijingToday();
  const loading = loadedKey !== pageKey(cursor, statusFilter);

  useEffect(() => {
    let current = true;
    let inFlight = false;
    const key = pageKey(cursor, statusFilter);
    const read = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const result = await runCommand<OrderHistoryPage>("orderHistory", { limit: 20, cursor, status: statusFilter });
        if (current && result) setPage(result);
      } finally {
        inFlight = false;
        if (current) setLoadedKey(key);
      }
    };
    void read();
    const timer = monitoring ? window.setInterval(() => void read(), 5000) : null;
    return () => { current = false; if (timer !== null) window.clearInterval(timer); };
  }, [runCommand, cursor, statusFilter, orderUpdated, monitoring]);

  const showDetail = async (intentId: string) => {
    const result = await runCommand<OrderHistoryDetail>("orderDetail", { intent_id: intentId });
    if (result) { setDetail(result); setReplacementDeadline(undefined); }
  };
  const refresh = () => {
    setCursor(null); setDetail(null); setRefreshing(true);
    void runCommand<OrderHistoryPage>("orderHistory", { limit: 20, cursor: null, status: statusFilter })
      .then(result => { if (result) { setPage(result); setLoadedKey(pageKey(null, statusFilter)); } })
      .finally(() => setRefreshing(false));
  };
  const perform = (key: string, command: string, payload?: Record<string, unknown>) => {
    setPending(key);
    void (payload ? runCommand(command, payload) : runCommand(command)).then(refresh).finally(() => setPending(null));
  };
  const filterBy = (value: string | null) => { setStatusFilter(value); setCursor(null); };
  const canReview = (item: OrderHistorySummary) => item.recovery_required && !monitoring && activity?.state !== "busy";

  const cardActions = (item: OrderHistorySummary, compact = false) => <>
    {item.observing ? <Button size="small" loading={pending === "stop:" + item.intent_id}
      onClick={() => perform("stop:" + item.intent_id, "stopMonitor")}>停止本地核对</Button> : null}
    {canReview(item) ? <Button size="small" type="primary" loading={pending === "continue:" + item.intent_id}
      onClick={() => perform("continue:" + item.intent_id, "continueOrder", { intent_id: item.intent_id })}>继续核对</Button> : null}
    <Button size="small" type={compact ? "text" : "default"} icon={<History size={13} aria-hidden="true" />}
      onClick={() => void showDetail(item.intent_id)}>查看时间线</Button>
  </>;

  const grouped = groups.map(group => ({ ...group, items: page.items.filter(item => orderGroup(item) === group.id) }))
    .filter(group => group.items.length);
  const attention = grouped.find(group => group.id === "attention")?.items.length ?? 0;
  const summary = detail?.summary;
  const detailStep = summary ? nextStep(summary) : null;

  return <div className="order-center">
    <header className="order-toolbar">
      <p className="order-summary" aria-live="polite">
        {loading ? "正在读取…" : page.items.length ? <><span><strong>{page.items.length}</strong> 条订单</span>
          {attention ? <span className="order-summary-attention"><strong>{attention}</strong> 条需要你处理</span> : null}</> : null}
      </p>
      <div className="order-toolbar-actions">
        <Select aria-label="按状态筛选" prefix={<ListFilter size={14} aria-hidden="true" />} value={statusFilter ?? "all"}
          onChange={value => filterBy(value === "all" ? null : value)} options={filterOptions} popupMatchSelectWidth={false} />
        <Button icon={<RefreshCw size={14} aria-hidden="true" />} loading={refreshing} onClick={refresh}>刷新</Button>
      </div>
    </header>

    {loading ? <><p className="sr-only" role="status">正在读取订单记录…</p><Skeleton /></> : page.items.length === 0 ?
      <div className="order-empty">
        <span className="order-empty-icon">{statusFilter ? <SearchX size={20} aria-hidden="true" /> : <ReceiptText size={20} aria-hidden="true" />}</span>
        {statusFilter ? <><strong>没有「{statusLabels[statusFilter] ?? statusFilter}」的订单</strong>
          <span>换个状态，或查看全部订单。</span>
          <Button size="small" onClick={() => filterBy(null)}>查看全部订单</Button></>
          : <><strong>暂无订单</strong><span>自动提交或候补的订单会出现在这里。</span></>}
      </div> :
      grouped.map(group => <section key={group.id} className={"order-section is-" + group.id} aria-labelledby={"order-group-" + group.id}>
        <h2 className="order-section-title" id={"order-group-" + group.id}>
          <i className={group.tone === "neutral" ? "lamp" : "lamp " + group.tone} aria-hidden="true" />{group.title}
          <span className="order-section-count">{group.items.length}</span>
        </h2>
        {group.id === "ended"
          ? <div className="order-row-list">{group.items.map(item => <OrderRow key={item.intent_id} item={item} actions={cardActions(item, true)} />)}</div>
          : <div className="order-history-list">{group.items.map(item =>
            <OrderTicket key={item.intent_id} item={item} group={group.id} actions={cardActions(item)} today={today} />)}</div>}
      </section>)}

    {!loading && (cursor || page.next_cursor) ? <nav className="order-pager" aria-label="订单分页">
      {cursor ? <Button onClick={() => { setCursor(null); setDetail(null); }}>回到最新</Button> : null}
      {page.next_cursor ? <Button onClick={() => { setCursor(page.next_cursor); setDetail(null); }}>
        下一页<ChevronRight size={14} aria-hidden="true" /></Button> : null}
    </nav> : null}

    <Drawer
      open={Boolean(detail)}
      onClose={() => setDetail(null)}
      size={520}
      className="order-drawer"
      title={summary ? <span className="order-drawer-title">
        <span className="order-drawer-route"><strong className="order-train">{summary.train_code}</strong>
          <span>{summary.from_station} → {summary.to_station}</span></span>
        <StatusBadge status={summary.status} kind={summary.kind} />
      </span> : null}
      footer={summary && canReview(summary) ? <div className="order-drawer-actions">
        <Button type="primary" loading={pending === "continue:" + summary.intent_id}
          onClick={() => perform("continue:" + summary.intent_id, "continueOrder", { intent_id: summary.intent_id })}>继续处理／核对</Button>
        {["unknown", "verification"].includes(summary.status) ? <Button loading={pending === "dismiss:" + summary.intent_id}
          onClick={() => perform("dismiss:" + summary.intent_id, "dismissOrder", { intent_id: summary.intent_id })}>
          结束本地核对（不取消官方订单）</Button> : null}
      </div> : null}
    >
      {detail && summary ? <section className="order-detail" aria-label="订单时间线">
        <p className="order-detail-meta">
          <span className="order-date" title={summary.date}>{tripDate(summary.date)}</span>
          <span>{kindLabel(summary)}</span><span>{summary.seat}</span>
          {summary.order_id ? <span>单号 <span className="mono">{summary.order_id}</span></span> : <span>尚未取得官方单号</span>}
        </p>
        <dl className="order-detail-status">
          <div><dt>本地结果</dt><dd>{statusLabel(summary.status, summary.kind)}</dd></div>
          <div><dt>官方状态</dt><dd>{officialSummary(summary)}</dd></div>
          <div><dt>最近核对</dt><dd>{time(summary.last_checked_at)} · {summary.observing ? "本地观察中" : "当前未观察"}
            {summary.last_check_status ? ` · ${checkResult(summary.last_check_status)}` : ""}</dd></div>
        </dl>
        {detailStep ? <p className="order-callout wait"><ArrowRight size={14} aria-hidden="true" />{detailStep}</p> : null}
        {summary.kind === "alternate" ? <div className="order-detail-block">
          <h3>候补条件</h3>
          <AlternateReview review={summary.review} deadline={summary.deadline} windows={summary.new_train_windows} />
        </div> : null}
        {canReview(summary) && !summary.order_id && summary.review?.deadline_reselection ?
          <div className="order-reselect" role="group" aria-label="重选截止兑现时间">
            <strong>重选截止兑现时间</strong>
            <p>原截止时间不在当前官网选项中或未能回读。选择本次官网提供的选项后，将继续原方案。</p>
            <div className="order-reselect-controls">
              <Select aria-label="原候补截止兑现时间" placeholder="选择本次官网选项" value={replacementDeadline}
                options={[...new Set((summary.review.deadline_options ?? []).map(canonicalDeadline))].map(value => ({ value, label: value }))}
                onChange={setReplacementDeadline} />
              <Button type="primary" disabled={!replacementDeadline || Boolean(busy)} loading={pending === "reselect:" + summary.intent_id}
                onClick={() => perform("reselect:" + summary.intent_id,
                "continueOrder", { intent_id: summary.intent_id, alternate_deadline: replacementDeadline })}>保存截止选项并继续原方案</Button>
            </div>
          </div> : null}
        {summary.status === "dismissed" ? <p className="order-callout"><Info size={14} aria-hidden="true" />已结束本地核对；此操作不等于取消官方订单。</p> : null}
        {!detail.history_complete ? <p className="order-callout" role="status"><Info size={14} aria-hidden="true" />历史事件不完整；缺失的时间不会推测补齐。</p> : null}
        {detail.events_truncated ? <p className="order-callout" role="status"><Info size={14} aria-hidden="true" />仅显示最近 500 条事件，更早记录仍保存在本地。</p> : null}
        <div className="order-detail-block">
          <h3>处理时间线{detail.events.length ? <small>最新在前 · {detail.events.length} 条</small> : null}</h3>
          {detail.events.length ? <Timeline events={detail.events} /> : <p className="order-callout">暂无事件记录。</p>}
        </div>
      </section> : null}
    </Drawer>
  </div>;
}
