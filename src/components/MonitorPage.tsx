import { Alert, Button, Switch } from "antd";
import { useEffect, useState } from "react";
import {
  Activity,
  Bell,
  BellRing,
  Clock3,
  Lock,
  MonitorPlay,
  Play,
  Radar,
  RefreshCw,
  Square,
  Timer,
  TrainFront,
} from "lucide-react";
import { useRailWatchStore } from "../store/useRailWatchStore";
import { displayedConfig, taskLabels } from "../lib/taskDisplay";
import { executionReference, getDateRangeStatus, useBeijingToday } from "../lib/tripDate";
import type { QueryResultRow, TicketHit } from "../types";
import type { CommandRunner } from "./componentTypes";

function formatTripDate(date: string) {
  if (!date) return "—";
  const parsed = new Date(`${date}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return date;
  const weekday = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"][parsed.getDay()];
  return `${parsed.getMonth() + 1}月${parsed.getDate()}日 ${weekday}`;
}

function useClock() {
  const [now, setNow] = useState(Date.now);
  useEffect(() => { const id = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(id); }, []);
  return now;
}

function ResultRow({ row, index }: { row: QueryResultRow; index: number }) {
  const hasTicket = row.raw.includes("有") || row.raw.includes("张");
  const isSoldOut = row.raw.includes("无") || row.raw.includes("候补");
  return (
    <div className={`dispatch-row ${hasTicket ? "has-ticket" : isSoldOut ? "sold-out" : ""}`} style={{ animationDelay: `${index * 40}ms` }}>
      <div className="dispatch-train-code">
        <TrainFront size={14} />
        <strong>{row.train}</strong>
      </div>
      <div className="dispatch-raw">{row.raw}</div>
      <div className="dispatch-status-dot">
        {hasTicket ? (
          <span className="dot-available" />
        ) : isSoldOut ? (
          <span className="dot-sold" />
        ) : (
          <span className="dot-unknown" />
        )}
      </div>
    </div>
  );
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

export function MonitorPage({ busy, runCommand }: { busy: string | null; runCommand: CommandRunner }) {
  const draftConfig = useRailWatchStore((state) => state.config);
  const status = useRailWatchStore((state) => state.status);
  const results = useRailWatchStore((state) => state.results);
  const hits = useRailWatchStore((state) => state.hits);
  const monitorLoops = useRailWatchStore((state) => state.monitorLoops);
  const setConfig = useRailWatchStore((state) => state.setConfig);
  const lastHumanAction = useRailWatchStore((state) => state.lastHumanAction);
  const clearHumanAction = useRailWatchStore((state) => state.clearHumanAction);

  const config = displayedConfig(draftConfig, status);
  const now = useClock();
  const today = useBeijingToday();
  const windowDays = useRailWatchStore((state) => state.runtime.date_policy?.presale_window_days);
  const dateRange = getDateRangeStatus(draftConfig.date, draftConfig.date_range, executionReference(draftConfig, today), windowDays);
  const seconds = status.task?.started_at ? Math.max(0, Math.floor(now / 1000 - status.task.started_at)) : 0;
  const elapsed = [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60].map(value => String(value).padStart(2, "0")).join(":");
  const countdown = status.task?.next_query_at ? `${Math.max(0, Math.ceil(status.task.next_query_at - now / 1000))}s` : (status.task?.status === "querying" ? "查询中" : "—");
  const fromStation = config.from_station_cn || "未设置";
  const toStation = config.to_station_cn || "未设置";
  const tripDate = formatTripDate(config.date);
  const trainPref = config.train_code || "不限";
  const seatPref = config.seat_keyword || (config.seat_prefer === "无偏好" ? "" : config.seat_prefer) || "不限";
  const autoSubmitEnabled = config.auto_submit;
  const autoAlternateEnabled = config.auto_alternate;

  const order = status.order;
  const unresolvedOrder = Boolean(order?.status && (order.recovery_required ||
    (["not_submitted", "sold_out"].includes(order.status) ? !order.no_order : !["fulfilled", "cancelled", "expired", "failed"].includes(order.status))));
  const canStart = Boolean(draftConfig.from_station_cn.trim() && draftConfig.to_station_cn.trim() && dateRange.valid.length && !status.monitoring && !unresolvedOrder && (!draftConfig.timer_enabled || draftConfig.sale_at));
  const canStop = status.monitoring;

  return (
    <div className="signal-tower">
      {/* ── Command Header ── */}
      <section className="st-command-header">
        <div className="st-signal-orb-wrapper">
          <div className={`st-signal-orb ${status.monitoring ? "active" : status.query_ready ? "armed" : "idle"}`}>
            <Radar size={26} />
          </div>
          {status.monitoring ? <span className="st-pulse-ring" /> : null}
        </div>
        <div className="st-signal-copy">
          <h2>{taskLabels[status.task?.status || ""] || (canStart ? "监控就绪" : "等待就绪")}</h2>
          <p>{status.monitoring ? status.status_message : canStart ? "行程已配置，可启动监控" : "请配置有效的行程日期"}</p>
        </div>
        <div className="st-command-actions">
          <Button
            className="st-btn-start"
            disabled={!canStart}
            icon={<Play size={15} />}
            loading={busy === "startMonitor"}
            onClick={() => void runCommand("startMonitor", { config: draftConfig })}
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
        </div>
      </section>

      {order?.status ? <Alert
        type={order.status === "fulfilled" || order.status === "active" ? "success" : "warning"}
        showIcon
        message={order.label || taskLabels[order.stage || order.status] || "订单待核对"}
        description={<div>
          <p>{order.intent?.train_code} · {order.intent?.date} · {order.intent?.seat}{order.order_id ? ` · 订单 ${order.order_id}` : ""}</p>
          <p>{order.reason || (order.status === "pending_payment" ? "请在官方页面完成支付；候补预付款支付后才生效。" : "状态以匹配的官方订单证据为准。")}</p>
          {unresolvedOrder ? <Button disabled={status.monitoring} loading={busy === "continueOrder"}
            onClick={() => void runCommand("continueOrder")}>继续处理／核对订单</Button> : null}
        </div>}
      /> : null}
      <p>实验性购票辅助：核验与支付需人工完成，发现现票不代表订单已创建。</p>

      {status.monitoring ? <p role="status">运行中使用启动时的行程配置；表单修改将在下次运行生效。</p> : null}
      {/* ── Metrics Signal Strip ── */}
      <section className="st-metrics-strip">
        <div className="st-metric">
          <Timer size={14} />
          <em>运行时间</em>
          <strong className="st-mono">{status.monitoring ? elapsed : "—"}</strong>
        </div>
        <div className="st-metric">
          <RefreshCw size={14} className={status.monitoring ? "spin-slow" : ""} />
          <em>查询次数</em>
          <strong className="st-mono">{monitorLoops}</strong>
        </div>
        <div className="st-metric">
          <Bell size={14} />
          <em>命中记录</em>
          <strong className={`st-mono ${hits.length > 0 ? "st-accent-green" : ""}`}>{hits.length}</strong>
        </div>
        <div className="st-metric">
          <Clock3 size={14} />
          <em>下次刷新</em>
          <strong className="st-mono">{status.monitoring ? countdown : "—"}</strong>
        </div>
        <div className="st-metric">
          <Activity size={14} />
          <em>刷新间隔</em>
          <strong className="st-mono">{config.interval}s</strong>
        </div>
      </section>

      {/* ── Two-Column Body ── */}
      <div className="st-body">
        {/* Left: Results */}
        <section className="st-results-panel">
          <div className="st-panel-head">
            <h3>
              <MonitorPlay size={15} />
              查询结果
            </h3>
            <span className="st-result-count">{results.length} 条</span>
          </div>
          {results.length === 0 ? (
            <div className="st-empty-results">
              <Radar size={32} />
              <strong>暂无查询结果</strong>
              <span>启动监控后将在此显示实时查询数据</span>
            </div>
          ) : (
            <div className="st-dispatch-board">
              {results.map((row, index) => (
                <ResultRow key={`${row.train}-${index}`} row={row} index={index} />
              ))}
            </div>
          )}
        </section>

        {/* Right: Hits + Config */}
        <aside className="st-side-panel">
          {/* Hit Feed */}
          <div className="st-hit-feed">
            <div className="st-panel-head">
              <h3>
                <BellRing size={15} />
                命中记录
              </h3>
              {hits.length > 0 ? <span className="st-hit-badge">{hits.length}</span> : null}
            </div>
            {hits.length === 0 ? (
              <div className="st-empty-hits">
                <Bell size={24} />
                <span>暂无命中</span>
              </div>
            ) : (
              <div className="st-hit-list">
                {hits.map((hit, index) => (
                  <HitCard key={`${hit.train_code}-${hit.seat_type}-${index}`} hit={hit} />
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
                自动提交 <strong>{autoSubmitEnabled ? "已启用" : "关闭"}</strong>
              </span>
            </label>
            <label className="st-flag-row">
              <Switch checked={autoAlternateEnabled} disabled size="small" />
              <span>
                自动候补 <strong>{autoAlternateEnabled ? "已启用" : "关闭"}</strong>
              </span>
            </label>
          </div>
        </aside>
      </div>

      {lastHumanAction ? (
        <Alert
          className="st-human-action"
          type="warning"
          showIcon
          closable
          message={lastHumanAction.title}
          description={lastHumanAction.message}
          onClose={clearHumanAction}
        />
      ) : null}
    </div>
  );
}
