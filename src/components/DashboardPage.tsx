import { needsRehearsal, rehearsalExpired } from "../lib/rehearsal";
import { tripFingerprint } from "../store/railwatchStore";
import { useMemo } from "react";
import { Button } from "antd";
import {
  ArrowRight,
  ArrowUpRight,
  Bell,
  Check,
  Clock3,
  Database,
  History,
  Lock,
  Pencil,
  ScrollText,
  Search,
  UserRound,
} from "lucide-react";
import { useRailWatchStore } from "../store/useRailWatchStore";
import {
  executionReference,
  getDateRangeStatus,
  getTripDateStatus,
  useBeijingToday,
} from "../lib/tripDate";
import { displayedConfig } from "../lib/taskDisplay";
import { dashboardAction, hasUnresolvedOrder } from "../lib/dashboardState";
import { countdown } from "../lib/saleCalendar";
import { automationConfigIssue } from "../lib/automationReadiness";
import { formatEventTime, presentEventLogs } from "../lib/formatEventLog";
import { useClock } from "../lib/useClock";
import type { RailWatchConfig, RailWatchStatus } from "../types";
import { DepartureBoard, TrainCodes, type BoardTone } from "./DepartureBoard";
import type { WorkflowStep } from "./DisplayPrimitives";
import { TripDateWarning } from "./DisplayPrimitives";
import { SaleCalendar } from "./SaleCalendar";

function formatTripDate(date: string) {
  if (!date) {
    return "未设置";
  }

  const parsed = new Date(`${date}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) {
    return date;
  }

  const weekday = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"][
    parsed.getDay()
  ];
  return `${parsed.getMonth() + 1}月${parsed.getDate()}日 ${weekday}`;
}

function getWorkflowSteps(
  status: RailWatchStatus,
  hasHits: boolean,
): WorkflowStep[] {
  const steps: WorkflowStep[] = [
    {
      label: "环境",
      description: status.environment_ready ? "检查完成" : "等待检查",
      icon: Database,
      state: status.environment_ready ? "done" : "current",
    },
    {
      label: "登录",
      description: status.login_ready ? "已登录" : "未登录",
      icon: UserRound,
      state: !status.environment_ready
        ? "pending"
        : status.login_ready
          ? "done"
          : "current",
    },
    {
      label: "查询",
      description: status.query_ready ? "就绪" : "待配置",
      icon: Search,
      state: !status.login_ready
        ? "pending"
        : status.query_ready
          ? "done"
          : "current",
    },
    {
      label: "购票监控",
      description: status.monitoring ? "运行中" : "未运行",
      icon: Clock3,
      state: !status.query_ready
        ? "pending"
        : status.monitoring || hasHits
          ? "done"
          : "current",
    },
    {
      label: "命中",
      description: hasHits ? "发现记录" : "0 条记录",
      icon: Bell,
      state: hasHits ? "current" : "pending",
    },
  ];
  let currentIndex = -1;
  for (let index = steps.length - 1; index >= 0; index -= 1) {
    if (steps[index].state === "current") {
      currentIndex = index;
      break;
    }
  }

  return steps.map((step, index) => {
    if (step.state !== "current" || index === currentIndex) {
      return step;
    }

    return { ...step, state: "done" };
  });
}

function boardStatus(status: RailWatchStatus): {
  tone: BoardTone;
  label: string;
  live: boolean;
} {
  if (hasUnresolvedOrder(status.order))
    return { tone: "wait", label: "订单待处理", live: false };
  if (status.error_message) return { tone: "stop", label: "监控异常", live: false };
  if (status.monitoring && status.task?.status === "waiting")
    return { tone: "wait", label: "等待定时启动", live: false };
  if (status.monitoring) return { tone: "go", label: "监控运行中", live: true };
  return { tone: "idle", label: "监控未运行", live: false };
}

function formatClockTime(timestamp: number) {
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).format(new Date(timestamp));
}

function boardDisplay(
  config: RailWatchConfig,
  status: RailWatchStatus,
  daysFromToday: number | null,
  loops: number,
  now: number,
) {
  if (status.monitoring && status.task?.started_at) {
    const seconds = Math.max(0, Math.floor(now / 1000 - status.task.started_at));
    return {
      caption: "已运行",
      value: [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60]
        .map((value) => String(value).padStart(2, "0"))
        .join(":"),
      note: `已查询 ${loops} 次`,
      tone: "go" as const,
    };
  }
  const saleAt = config.timer_enabled && config.sale_at ? Date.parse(config.sale_at) : NaN;
  if (Number.isFinite(saleAt) && saleAt > now) {
    return {
      caption: "距定时开售",
      value: countdown(saleAt, now),
      note: `北京时间 ${formatClockTime(saleAt)} 起售`,
      tone: "led" as const,
    };
  }
  if (daysFromToday === null) return undefined;
  return {
    caption: "出发日期",
    value: `${config.date.slice(5, 7)}/${config.date.slice(8, 10)}`,
    note:
      daysFromToday < 0
        ? "已过出发日期"
        : daysFromToday === 0
          ? "今天出发"
          : daysFromToday === 1
            ? "明天出发"
            : `${daysFromToday} 天后出发`,
    tone: daysFromToday < 0 ? ("stop" as const) : ("led" as const),
  };
}

export function DashboardPage() {
  const status = useRailWatchStore((state) => state.status);
  const draft = useRailWatchStore((state) => state.config);
  const config = displayedConfig(draft, status);
  const trains = config.train_code.split(/[,，、\s]+/).filter(Boolean);
  const hits = useRailWatchStore((state) => state.hits);
  const logs = useRailWatchStore((state) => state.logs);
  const openLogs = useRailWatchStore((state) => state.setEventPanelVisible);
  const recentEvents = useMemo(() => presentEventLogs(logs, "全部").slice(0, 5), [logs]);
  const loops = useRailWatchStore((state) => state.monitorLoops);
  const human = useRailWatchStore((state) => state.lastHumanAction);
  const navigate = useRailWatchStore((state) => state.setActivePage);
  const windowDays = useRailWatchStore(
    (state) => state.runtime.date_policy?.presale_window_days,
  );
  const seatCapabilities = useRailWatchStore((state) => state.runtime.seat_capabilities);
  const today = useBeijingToday();
  const now = useClock();
  const range = getDateRangeStatus(
    config.date,
    config.date_range,
    executionReference(config, today),
    windowDays,
  );
  const tripValid = Boolean(
    config.from_station_cn.trim() &&
      config.to_station_cn.trim() &&
      range.valid.length &&
      !automationConfigIssue(config, seatCapabilities) &&
      (!config.timer_enabled || config.sale_at),
  );
  const rehearsal = useRailWatchStore(s => s.rehearsal);
  const rehearsalEnabled = useRailWatchStore(s => s.rehearsalEnabled);
  const action = dashboardAction(status, human, tripValid, rehearsalEnabled && needsRehearsal(config, rehearsal.report, rehearsalExpired(rehearsal.fingerprint, tripFingerprint(config))));
  const steps = getWorkflowSteps(status, hits.length > 0);
  const nextQuery = !status.monitoring
    ? "—"
    : status.task?.status === "querying"
      ? "查询中"
      : status.task?.next_query_at
        ? `${Math.max(0, Math.ceil(status.task.next_query_at - now / 1000))} 秒`
        : "—";
  const passengerCount =
    config.passengers.split(/[,，、]/).filter(Boolean).length ||
    config.passenger_count ||
    1;
  const seatText =
    config.seat_keyword ||
    (config.seat_prefer === "无偏好" ? "席别不限" : config.seat_prefer);
  const dateStatus = getTripDateStatus(config.date, today, windowDays);
  const board = boardStatus(status);
  const display = boardDisplay(config, status, dateStatus.daysFromToday, loops, now);
  const autoSubmit = status.monitoring
    ? status.auto_submit_enabled || config.auto_submit
    : config.auto_submit;
  const autoAlternate = status.monitoring
    ? status.auto_alternate_enabled || config.auto_alternate
    : config.auto_alternate;
  return (
    <div className="dashboard" aria-label="RailWatch 仪表盘">
      <DepartureBoard
        label="当前行程"
        className="dashboard-board"
        kicker={status.monitoring ? "运行中的行程" : "当前行程"}
        tone={board.tone}
        live={board.live}
        status={board.label}
        from={config.from_station_cn || "出发站"}
        to={config.to_station_cn || "到达站"}
        fromNote={`${formatTripDate(config.date)} · ${config.date_range || "单日"}`}
        toNote={`${seatText} · 乘客 ${passengerCount} 位`}
        trackLabel={trains.length ? `${trains.length} 车次` : "车次不限"}
        display={display}
        facts={[
          {
            label: "车次",
            value: <TrainCodes codes={trains} highlighted={hits.map((hit) => hit.train_code)} />,
          },
          { label: "席别", value: seatText },
          { label: "乘客", value: `${passengerCount} 位 · 票种待官方页核对` },
        ]}
        actions={
          <>
            <Button
              type="text"
              icon={<History size={16} aria-hidden="true" />}
              aria-label="查看订单历史与核对时间线"
              onClick={() => navigate("订单中心")}
            >
              订单历史
            </Button>
            <Button
              icon={<Pencil size={16} aria-hidden="true" />}
              onClick={() => navigate("行程设置", "trip-basics")}
            >
              编辑行程
            </Button>
          </>
        }
      >
        <TripDateWarning message={dateStatus.warning} />
      </DepartureBoard>
      <div className={"next-card " + action.tone}>
        <section className="next-action" aria-label="下一步">
          <div className="next-action-copy">
            <span className="eyebrow">
              {action.tone === "warning" ? "需要你处理" : "下一步"}
            </span>
            <h2>{action.title}</h2>
            <p>{action.description}</p>
          </div>
          <Button
            type="primary"
            icon={<ArrowRight size={16} />}
            onClick={() => navigate(action.page, action.section)}
          >
            {action.label}
          </Button>
        </section>
        <ol className="workflow-stepper" aria-label="监控流程">
          {steps.map((step) => (
            <li
              key={step.label}
              className={"workflow-step " + step.state}
              aria-current={step.state === "current" ? "step" : undefined}
            >
              <span className="workflow-dot" aria-hidden="true">
                {step.state === "done" ? <Check size={10} strokeWidth={3} /> : null}
              </span>
              <strong>{step.label}</strong>
              <small>{step.description}</small>
            </li>
          ))}
        </ol>
      </div>
      <div className="dashboard-lower">
        <section className="panel">
          <div className="section-heading">
            <h2>监控概况</h2>
            <span className="subtle-label">
              {status.monitoring ? "实时更新" : "尚未运行"}
            </span>
          </div>
          <div className="dashboard-metrics">
            <div>
              <Search size={16} />
              <span>查询次数</span>
              <strong>{loops}</strong>
            </div>
            <div>
              <Clock3 size={16} />
              <span>下次查询</span>
              <strong>{nextQuery}</strong>
            </div>
            <div>
              <Bell size={16} />
              <span>命中记录</span>
              <strong>{hits.length}</strong>
            </div>
          </div>
        </section>
        <section className="panel recent-hits">
          <div className="section-heading">
            <h2>最近命中</h2>
            <span className="subtle-label">{hits.length} 条记录</span>
          </div>
          {hits.length ? (
            <div className="recent-hit-list">
              {hits
                .slice(-3)
                .reverse()
                .map((hit, index) => (
                  <div className="recent-hit" key={index}>
                    <Bell size={16} />
                    <div>
                      <strong>
                        {hit.train_code} · {hit.seat_type}
                      </strong>
                      <p>{hit.label || hit.status}</p>
                    </div>
                  </div>
                ))}
            </div>
          ) : (
            <div className="empty-inline">
              <Bell size={24} />
              <div>
                <strong>暂无命中记录</strong>
                <p>符合行程条件的余票将在此显示。</p>
              </div>
            </div>
          )}
        </section>
      </div>
      <SaleCalendar station={config.from_station_cn} tripDate={config.date} windowDays={windowDays} now={now} />
      <section className="dashboard-events" aria-label="最近活动">
        <div className="section-heading">
          <h2><ScrollText size={15} /> 最近活动</h2>
          <Button type="text" size="small" onClick={() => openLogs(true)}>
            查看全部日志 <ArrowUpRight size={14} />
          </Button>
        </div>
        {recentEvents.length ? (
          <ol className="activity-list">
            {recentEvents.map((entry) => (
              <li key={entry.id}>
                <time dateTime={entry.time} title={`北京时间 · ${formatEventTime(entry.time)}`}>{formatEventTime(entry.time)}</time>
                <span className={`event-level ${entry.tone}`}>{entry.label}</span>
                <span className="activity-message"><strong>{entry.title}</strong>{entry.detail ? <span>{entry.detail}</span> : null}</span>
              </li>
            ))}
          </ol>
        ) : (
          <div className="activity-empty"><ScrollText size={19} /><span>暂无运行事件</span><small>环境检查、查询和订单动态将按时间记录。</small></div>
        )}
      </section>
      <section
        className={
          "automation-summary" + (autoSubmit || autoAlternate ? " enabled" : "")
        }
        aria-label="自动化状态"
      >
        <Lock size={16} />
        <div>
          <strong>
            {autoSubmit || autoAlternate ? "自动化已启用" : "自动化已关闭"}
          </strong>
          <p>
            {autoSubmit || autoAlternate
              ? `自动提交${autoSubmit ? "已启用" : "关闭"} · 自动候补${autoAlternate ? "已启用" : "关闭"}；核验与支付仍需人工完成。`
              : "当前仅关注余票变化，自动提交与自动候补均未启用。"}
          </p>
        </div>
        <Button
          type="text"
          onClick={() => navigate("行程设置", "trip-automation")}
        >
          配置自动化 <ArrowUpRight size={14} />
        </Button>
      </section>
    </div>
  );
}
