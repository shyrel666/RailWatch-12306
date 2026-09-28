import { useState } from "react";
import { Alert, Button, Switch } from "antd";
import { useClock } from "../lib/useClock";
import { hasUnresolvedOrder } from "../lib/dashboardState";
import {
  Activity,
  Bell,
  BellRing,
  Clock3,
  Lock,
  Play,
  Radar,
  RefreshCw,
  Square,
  Timer,
  TrainFront,
} from "lucide-react";
import { useRailWatchStore } from "../store/useRailWatchStore";
import { railwatchStore, tripFingerprint } from "../store/railwatchStore";
import { displayedConfig, taskLabels } from "../lib/taskDisplay";
import {
  executionReference,
  getDateRangeStatus,
  useBeijingToday,
} from "../lib/tripDate";
import type { TicketHit } from "../types";
import type { CommandRunner } from "./componentTypes";
import { QueryResults } from "./QueryResults";
import { queryTargets, selectableQueryTrains } from "../lib/queryResults";

function formatTripDate(date: string) {
  if (!date) return "—";
  const parsed = new Date(`${date}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return date;
  const weekday = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"][
    parsed.getDay()
  ];
  return `${parsed.getMonth() + 1}月${parsed.getDate()}日 ${weekday}`;
}

function HitCard({ hit }: { hit: TicketHit }) {
  return (
    <div className="hit-card">
      <div className="hit-card-indicator">
        <BellRing size={14} />
      </div>
      <div className="hit-card-body">
        <strong>
          {hit.train_code} · {hit.seat_type}
        </strong>
        <span>{hit.label || hit.status}</span>
        {hit.detail ? <small>{hit.detail}</small> : null}
      </div>
      <span className="hit-card-source">{hit.source}</span>
    </div>
  );
}

export function MonitorPage({
  busy,
  runCommand,
}: {
  busy: string | null;
  runCommand: CommandRunner;
}) {
  const [startError, setStartError] = useState("");
  const [selectionError, setSelectionError] = useState("");
  const draftConfig = useRailWatchStore((state) => state.config);
  const editRevision = useRailWatchStore((state) => state.editRevision);
  const status = useRailWatchStore((state) => state.status);
  const results = useRailWatchStore((state) => state.results);
  const queryViews = useRailWatchStore((state) => state.queryViews);
  const activeQuery = useRailWatchStore((state) => state.activeQuery);
  const queryConfig = useRailWatchStore((state) => state.queryConfig);
  const setConfig = useRailWatchStore((state) => state.setConfig);
  const setActivePage = useRailWatchStore((state) => state.setActivePage);
  const manualPending = useRailWatchStore((state) => state.manualQueryPending);
  const manualError = useRailWatchStore((state) => state.manualQueryError);
  const hits = useRailWatchStore((state) => state.hits);
  const monitorLoops = useRailWatchStore((state) => state.monitorLoops);
  const lastHumanAction = useRailWatchStore((state) => state.lastHumanAction);
  const clearHumanAction = useRailWatchStore((state) => state.clearHumanAction);

  const config = displayedConfig(draftConfig, status);
  const now = useClock();
  const today = useBeijingToday();
  const windowDays = useRailWatchStore(
    (state) => state.runtime.date_policy?.presale_window_days,
  );
  const dateRange = getDateRangeStatus(
    draftConfig.date,
    draftConfig.date_range,
    executionReference(draftConfig, today),
    windowDays,
  );
  const seconds = status.task?.started_at
    ? Math.max(0, Math.floor(now / 1000 - status.task.started_at))
    : 0;
  const elapsed = [
    Math.floor(seconds / 3600),
    Math.floor(seconds / 60) % 60,
    seconds % 60,
  ]
    .map((value) => String(value).padStart(2, "0"))
    .join(":");
  const countdown = status.task?.next_query_at
    ? `${Math.max(0, Math.ceil(status.task.next_query_at - now / 1000))}s`
    : status.task?.status === "querying"
      ? "查询中"
      : "—";
  const fromStation = config.from_station_cn || "未设置";
  const toStation = config.to_station_cn || "未设置";
  const tripDate = formatTripDate(config.date);
  const trainPref = config.train_code || "不限";
  const seatPref =
    config.seat_keyword ||
    (config.seat_prefer === "无偏好" ? "" : config.seat_prefer) ||
    "不限";
  const autoSubmitEnabled = config.auto_submit;
  const autoAlternateEnabled = config.auto_alternate;

  const order = status.order;
  const unresolvedOrder = hasUnresolvedOrder(order);
  const canStart = Boolean(
    draftConfig.from_station_cn.trim() &&
      draftConfig.to_station_cn.trim() &&
      dateRange.valid.length &&
      !status.monitoring &&
      !unresolvedOrder &&
      (!draftConfig.timer_enabled || draftConfig.sale_at),
  );
  const canStop = status.monitoring;

  const startWithSummary = async () => {
    const snapshot = structuredClone(draftConfig);
    const dates = [...dateRange.valid];
    setStartError("");
    await runCommand("startMonitor", { config: snapshot, expected_dates: dates });
  };

  return (
    <div className="signal-tower">
      {/* ── Command Header ── */}
      <section
        className="st-command-header"
        id="monitor-controls"
        tabIndex={-1}
      >
        <div className="st-signal-orb-wrapper">
          <div
            className={`st-signal-orb ${status.monitoring ? "active" : status.query_ready ? "armed" : "idle"}`}
          >
            <Radar size={26} />
          </div>
        </div>
        <div className="st-signal-copy">
          <h2>
            {unresolvedOrder
              ? "当前订单待处理"
              : lastHumanAction
                ? "等待人工处理"
                : status.error_message
                  ? "监控异常"
                  : taskLabels[status.task?.status || ""] ||
                    (canStart ? "监控就绪" : "等待就绪")}
          </h2>
          <p>
            {unresolvedOrder
              ? "请先处理当前订单，再开始下一次监控"
              : lastHumanAction
                ? "请按照下方提示在官方页面继续操作"
                : status.error_message ||
                  (status.monitoring
                    ? status.status_message
                    : canStart
                      ? "行程已配置，可启动监控"
                      : "请配置有效的行程日期")}
          </p>
        </div>
        <div className="st-command-actions">
          <Button
            className="st-btn-start"
            disabled={!canStart}
            icon={<Play size={15} />}
            loading={busy === "startMonitor"}
            onClick={() => void startWithSummary()}
            type="primary"
          >
            启动监控
          </Button>
          {startError ? <span role="alert">{startError}</span> : null}
          <Button
            className="st-btn-stop"
            disabled={!canStop}
            icon={<Square size={15} />}
            loading={busy === "stopMonitor"}
            onClick={() => void runCommand("stopMonitor")}
            danger
          >
            停止
          </Button>
        </div>
      </section>

      {order?.status ? (
        <Alert
          id="monitor-attention"
          type={
            order.status === "fulfilled" || order.status === "active"
              ? "success"
              : "warning"
          }
          showIcon
          message={
            order.label ||
            taskLabels[order.stage || order.status] ||
            "订单待核对"
          }
          description={
            <div>
              {order.intent || order.order_id ? (
                <p>
                  {[
                    order.intent?.train_code,
                    order.intent?.date,
                    order.intent?.seat,
                    order.order_id ? `订单 ${order.order_id}` : null,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              ) : null}
              <p>
                {order.reason ||
                  (order.status === "pending_payment"
                    ? "请在官方页面完成支付；候补预付款支付后才生效。"
                    : "状态以匹配的官方订单证据为准。")}
              </p>
              {unresolvedOrder ? (
                <div className="st-command-actions">
                <Button
                  disabled={status.monitoring || busy !== null}
                  loading={busy === "continueOrder"}
                  onClick={() => void runCommand("continueOrder")}
                >
                  继续处理／核对订单
                </Button>
                {order.intent?.intent_id && ["unknown", "verification"].includes(order.status) ? (
                  <Button
                    disabled={status.monitoring || busy !== null}
                    loading={busy === "dismissOrder"}
                    onClick={() => void runCommand("dismissOrder", { intent_id: order.intent!.intent_id }, "已结束本次核对，可重新启动监控")}
                  >
                    结束本次核对
                  </Button>
                ) : null}
                </div>
              ) : null}
            </div>
          }
        />
      ) : null}
      {lastHumanAction ? (
        <Alert
          className="st-human-action"
          id="monitor-human"
          type="warning"
          showIcon
          closable
          message={lastHumanAction.title}
          description={lastHumanAction.message}
          onClose={clearHumanAction}
        />
      ) : null}
      <p>实验性购票辅助：核验与支付需人工完成，发现现票不代表订单已创建。</p>

      {status.monitoring ? (
        <p role="status">
          运行中使用启动时的行程配置；表单修改将在下次运行生效。
        </p>
      ) : null}
      {/* ── Metrics Signal Strip ── */}
      <section className="st-metrics-strip">
        <div className="st-metric">
          <Timer size={14} />
          <em>运行时间</em>
          <strong className="st-mono">
            {status.monitoring ? elapsed : "—"}
          </strong>
        </div>
        <div className="st-metric">
          <RefreshCw
            size={14}
            className={status.monitoring ? "spin-slow" : ""}
          />
          <em>查询次数</em>
          <strong className="st-mono">{monitorLoops}</strong>
        </div>
        <div className="st-metric">
          <Bell size={14} />
          <em>命中记录</em>
          <strong
            className={`st-mono ${hits.length > 0 ? "st-accent-green" : ""}`}
          >
            {hits.length}
          </strong>
        </div>
        <div className="st-metric">
          <Clock3 size={14} />
          <em>下次刷新</em>
          <strong className="st-mono">
            {status.monitoring ? countdown : "—"}
          </strong>
        </div>
        <div className="st-metric">
          <Activity size={14} />
          <em>刷新间隔</em>
          <strong className="st-mono">{config.interval}s</strong>
        </div>
      </section>

      {/* ── Two-Column Body ── */}
      {status.monitoring && tripFingerprint(draftConfig) !== tripFingerprint(config) ? <div className="st-running-draft-note" role="status">
        本次执行：{config.date} · {config.from_station_cn} → {config.to_station_cn} · {config.train_code || "不限车次"}；
        当前草稿：{draftConfig.date} · {draftConfig.from_station_cn} → {draftConfig.to_station_cn} · {draftConfig.train_code || "不限车次"}。草稿修改仅在下一次任务生效。
      </div> : null}
      {selectionError ? <p role="alert">{selectionError}</p> : null}
      <div className="st-body">
        {/* Left: Results */}
        <QueryResults views={queryViews} rows={results} config={queryConfig ?? config} editableRoute={draftConfig}
          onSelectTrains={trains => {
            const state = railwatchStore.getState();
            const allowed = selectableQueryTrains(state.queryViews, state.config);
            if (state.editRevision !== editRevision || !trains.length || trains.some(train => !allowed.has(train))) {
              setSelectionError("草稿或查询结果已变化，请重新选择当前路线的车次。");
              return;
            }
            const current = queryTargets(state.config.train_code.toUpperCase());
            setConfig({ train_code: [...new Set([...current, ...trains])].join(", ") });
            setSelectionError("");
            setActivePage("行程设置");
          }} status={status}
          now={now / 1000} pending={manualPending} error={manualError} activeQuery={activeQuery} />

        {/* Right: Hits + Config */}
        <aside className="st-side-panel">
          {/* Hit Feed */}
          <div className="st-hit-feed">
            <div className="st-panel-head">
              <h3>
                <BellRing size={15} />
                命中记录
              </h3>
              {hits.length > 0 ? (
                <span className="st-hit-badge">{hits.length}</span>
              ) : null}
            </div>
            {hits.length === 0 ? (
              <div className="st-empty-hits">
                <Bell size={24} />
                <span>暂无命中</span>
              </div>
            ) : (
              <div className="st-hit-list">
                {hits.map((hit, index) => (
                  <HitCard
                    key={`${hit.train_code}-${hit.seat_type}-${index}`}
                    hit={hit}
                  />
                ))}
              </div>
            )}
          </div>

          {/* Trip Config Summary */}
          <div className="st-config-summary">
            <div className="st-panel-head">
              <h3>
                <TrainFront size={15} />
                当前行程
              </h3>
            </div>
            <dl className="st-config-grid">
              <dt>路线</dt>
              <dd>
                {fromStation} → {toStation}
              </dd>
              <dt>日期</dt>
              <dd>{tripDate}</dd>
              <dt>车次</dt>
              <dd>{trainPref}</dd>
              <dt>席别</dt>
              <dd>{seatPref}</dd>
            </dl>
          </div>

          {/* Automation Flags */}
          <div className="st-automation-flags">
            <div className="st-panel-head">
              <h3>
                <Lock size={15} />
                自动化
              </h3>
            </div>
            <label className="st-flag-row">
              <Switch checked={autoSubmitEnabled} disabled size="small" />
              <span>
                自动提交{" "}
                <strong>{autoSubmitEnabled ? "已启用" : "关闭"}</strong>
              </span>
            </label>
            <label className="st-flag-row">
              <Switch checked={autoAlternateEnabled} disabled size="small" />
              <span>
                自动候补{" "}
                <strong>{autoAlternateEnabled ? "已启用" : "关闭"}</strong>
              </span>
            </label>
          </div>
        </aside>
      </div>
    </div>
  );
}
