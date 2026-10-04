import { RehearsalPanel } from "./RehearsalPanel";
import { useState } from "react";
import { Alert, Button, Switch } from "antd";
import { useClock } from "../lib/useClock";
import { hasUnresolvedOrder } from "../lib/dashboardState";
import { automationConfigIssue } from "../lib/automationReadiness";
import { DATE_STRATEGIES, dateStrategy, dateStrategySummary } from "../lib/dateStrategy";
import { orderPolicySummary } from "../lib/orderPolicy";
import { Bell, BellRing, Lock, Play, Square } from "lucide-react";
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
import { countdown as saleCountdown } from "../lib/saleCalendar";
import { DepartureBoard, TrainCodes, type BoardTone } from "./DepartureBoard";

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
  const rehearsalEnabled = useRailWatchStore(state => state.rehearsalEnabled);
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
  const seatPref =
    config.seat_keyword ||
    (config.seat_prefer === "无偏好" ? "" : config.seat_prefer) ||
    "不限";
  const autoSubmitEnabled = config.auto_submit;
  const autoAlternateEnabled = config.auto_alternate;

  const order = status.order;
  const unresolvedOrder = hasUnresolvedOrder(order);
  const seatCapabilities = useRailWatchStore(state => state.runtime.seat_capabilities);
  const automationIssue = automationConfigIssue(draftConfig, seatCapabilities);
  const canStart = Boolean(
    draftConfig.from_station_cn.trim() &&
      draftConfig.to_station_cn.trim() &&
      dateRange.valid.length &&
      !status.monitoring &&
      !unresolvedOrder &&
      !automationIssue &&
      (!draftConfig.timer_enabled || draftConfig.sale_at),
  );
  const canStop = status.monitoring;
  const trainCodes = queryTargets(config.train_code.toUpperCase());
  const headline = unresolvedOrder
    ? "当前订单待处理"
    : lastHumanAction
      ? "等待人工处理"
      : status.error_message
        ? "监控异常"
        : !status.monitoring && automationIssue
          ? "自动化配置待完善"
          : taskLabels[status.task?.status || ""] ||
            (canStart ? "监控就绪" : "等待就绪");
  const message = unresolvedOrder
    ? "请先处理当前订单，再开始下一次监控"
    : lastHumanAction
      ? "请按照下方提示在官方页面继续操作"
      : status.error_message ||
        (status.monitoring
          ? status.status_message
          : automationIssue ||
            (canStart ? "行程已配置，可启动监控" : "请配置有效的行程日期"));
  const waitingForSale = status.monitoring && status.task?.status === "waiting";
  const boardTone: BoardTone =
    unresolvedOrder || lastHumanAction
      ? "wait"
      : status.error_message
        ? "stop"
        : status.monitoring
          ? waitingForSale
            ? "wait"
            : "go"
          : automationIssue
            ? "wait"
            : "idle";
  const saleAt = config.timer_enabled && config.sale_at ? Date.parse(config.sale_at) : NaN;
  const display =
    waitingForSale && Number.isFinite(saleAt) && saleAt > now
      ? { caption: "距定时开售", value: saleCountdown(saleAt, now), note: "到点后自动开始查询", tone: "led" as const }
      : status.monitoring
        ? {
            caption: "已运行",
            value: elapsed,
            note: status.task?.status === "querying" ? "正在查询" : `已查询 ${monitorLoops} 次`,
            tone: "go" as const,
          }
        : { caption: "运行时间", value: "00:00:00", note: "监控未运行", tone: "dim" as const };
  const refreshProgress =
    status.monitoring && status.task?.next_query_at && config.interval > 0
      ? Math.min(1, Math.max(0, 1 - (status.task.next_query_at - now / 1000) / config.interval))
      : 0;

  const startWithSummary = async () => {
    if (!canStart) return;
    const snapshot = structuredClone(draftConfig);
    const dates = [...dateRange.valid];
    setStartError("");
    await runCommand("startMonitor", { config: snapshot, expected_dates: dates });
  };

  return (
    <div className="signal-tower">
      <DepartureBoard
        label="监控控制"
        id="monitor-controls"
        className="monitor-board"
        tone={boardTone}
        live={status.monitoring && boardTone === "go"}
        status={<h2>{headline}</h2>}
        message={message ? <p>{message}</p> : undefined}
        from={fromStation}
        to={toStation}
        trackLabel={trainCodes.length ? `${trainCodes.length} 车次` : "车次不限"}
        display={display}
        facts={[
          {
            label: "车次",
            value: <TrainCodes codes={trainCodes} highlighted={hits.map((hit) => hit.train_code)} />,
          },
          { label: "日期", value: `${tripDate} · ${config.date_range || "单日"}` },
          { label: "席别", value: seatPref },
        ]}
        actions={
          <>
            {!status.monitoring && automationIssue ? (
              <Button onClick={() => setActivePage("行程设置", "trip-basics")}>完善自动化配置</Button>
            ) : null}
            {startError ? <span role="alert">{startError}</span> : null}
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
          </>
        }
      />

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
      <p>购票辅助：核验与支付需人工完成，发现现票不代表订单已创建，订单状态以官方页面为准。</p>
      <p aria-label="本次日期策略">日期策略：{config.date_range === "单日" ? "单日查询" : DATE_STRATEGIES[dateStrategy(config)].label}。{dateStrategySummary(config)}</p>
      <p aria-label="本次候补与核对策略">{orderPolicySummary(config)}</p>

      {status.monitoring ? (
        <p role="status">
          运行中使用启动时的行程配置；表单修改将在下次运行生效。
        </p>
      ) : null}
      {/* ── Metrics Signal Strip ── */}
      {rehearsalEnabled ? <RehearsalPanel busy={busy} runCommand={runCommand} /> : null}
      <section className="st-metrics-strip" aria-label="运行指标">
        <div className="st-metric">
          <em>查询次数</em>
          <strong className="st-mono">{monitorLoops}</strong>
        </div>
        <div className="st-metric">
          <em>命中记录</em>
          <strong
            className={`st-mono ${hits.length > 0 ? "st-accent-green" : ""}`}
          >
            {hits.length}
          </strong>
        </div>
        <div className="st-metric">
          <em>下次刷新</em>
          <strong className="st-mono">
            {status.monitoring ? countdown : "—"}
          </strong>
          <span className="st-progress" aria-hidden="true">
            <i style={{ width: `${refreshProgress * 100}%` }} />
          </span>
        </div>
        <div className="st-metric">
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
