import { Button, Switch } from "antd";
import {
  Bell,
  CalendarDays,
  Check,
  Clock3,
  Database,
  Lock,
  MonitorPlay,
  Pause,
  Radar,
  Search,
  ShieldAlert,
  TrainFront,
  UserRound,
} from "lucide-react";
import { useRailWatchStore } from "../store/useRailWatchStore";
import type { RailWatchConfig, RailWatchPage, RailWatchStatus } from "../types";
import type { WorkflowStep } from "./DisplayPrimitives";

type RequestMode = "均衡模式" | "保守模式" | "快速模式";

function requestModeToSmartRate(mode: RequestMode) {
  return mode !== "保守模式";
}

function smartRateToRequestMode(smartRate: boolean, interval: number): RequestMode {
  if (!smartRate) {
    return "保守模式";
  }
  return interval <= 3 ? "快速模式" : "均衡模式";
}

function SegmentedControl<T extends string>({
  ariaLabel,
  onChange,
  options,
  value,
}: {
  ariaLabel: string;
  onChange: (value: T) => void;
  options: readonly T[];
  value: T;
}) {
  return (
    <div aria-label={ariaLabel} className="segmented-control" role="group">
      {options.map((option) => (
        <button
          aria-pressed={value === option}
          className={value === option ? "segmented-option active" : "segmented-option"}
          key={option}
          onClick={() => onChange(option)}
          type="button"
        >
          {option}
        </button>
      ))}
    </div>
  );
}

const riskLabel: Record<string, string> = {
  notice: "低风险",
  success: "低风险",
  active: "监控中",
  warning: "需注意",
  critical: "高风险",
};

const workflowShortText: Record<WorkflowStep["state"], string> = {
  current: "就绪",
  done: "已完成",
  pending: "未运行",
};

function normalizeRouteStation(station: string, fallback: string) {
  if (!station) {
    return fallback;
  }

  if (station === "北京") {
    return "北京南";
  }

  if (station === "上海") {
    return "上海虹桥";
  }

  return station;
}

function formatTripDate(date: string) {
  if (!date) {
    return "6月20日 周五";
  }

  const parsed = new Date(`${date}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) {
    return date;
  }

  const weekday = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"][parsed.getDay()];
  return `${parsed.getMonth() + 1}月${parsed.getDate()}日 ${weekday}`;
}

function formatCompactDate(dateLabel: string) {
  return dateLabel.split(" ")[0] || dateLabel;
}

function getWorkflowSteps(status: RailWatchStatus, hasHits: boolean): WorkflowStep[] {
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
      state: !status.environment_ready ? "pending" : status.login_ready ? "done" : "current",
    },
    {
      label: "查询",
      description: status.query_ready ? "就绪" : "待配置",
      icon: Search,
      state: !status.login_ready ? "pending" : status.query_ready ? "done" : "current",
    },
    {
      label: "购票监控",
      description: status.monitoring ? "运行中" : "未运行",
      icon: Clock3,
      state: !status.query_ready ? "pending" : status.monitoring || hasHits ? "done" : "current",
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

function getNextAction(status: RailWatchStatus): { description: string; label: string; page: RailWatchPage } {
  if (!status.environment_ready) {
    return {
      description: "先确认 ChromeDriver、浏览器和本机依赖，再进入登录与查询流程。",
      label: "检查环境",
      page: "系统设置",
    };
  }

  if (!status.login_ready) {
    return {
      description: "环境已经可用，下一步打开登录页并完成人工登录。",
      label: "去行程设置",
      page: "行程设置",
    };
  }

  if (!status.query_ready) {
    return {
      description: "登录状态已准备好，补齐行程后进行查询分析。",
      label: "完善行程",
      page: "行程设置",
    };
  }

  return {
    description: status.monitoring ? "监控正在运行，可到监控页查看刷新与查询结果。" : "查询分析完成，可以启动受控刷新。",
    label: status.monitoring ? "查看监控" : "去监控",
    page: "购票监控",
  };
}

export function DashboardPage() {
  const status = useRailWatchStore((state) => state.status);
  const config = useRailWatchStore((state) => state.config);
  const hits = useRailWatchStore((state) => state.hits);
  const setActivePage = useRailWatchStore((state) => state.setActivePage);
  const setConfig = useRailWatchStore((state) => state.setConfig);
  const hasHits = hits.length > 0;
  const workflowSteps = getWorkflowSteps(status, hasHits);
  const nextAction = getNextAction(status);
  const fromStation = normalizeRouteStation(config.from_station_cn, "北京南");
  const toStation = normalizeRouteStation(config.to_station_cn, "上海虹桥");
  const tripDate = formatTripDate(config.date);
  const compactTripDate = formatCompactDate(tripDate);
  const trainPreference = config.train_code || "G1234 等 4 个车次";
  const trainFamily = config.train_code ? trainPreference.replace(/[,，]/g, "、") : "G/D/C";
  const seatPreference = config.seat_keyword || (config.seat_prefer === "无偏好" ? "" : config.seat_prefer) || "二等座";
  const passengerText = config.passenger_count ? `成人 ${config.passenger_count}` : "成人 1";
  const riskTone =
    status.risk_level === "critical" ? "critical" : status.risk_level === "warning" ? "warning" : status.monitoring ? "active" : "safe";
  const analysisTitle = status.query_ready ? "查询就绪" : !status.environment_ready ? "检查环境" : !status.login_ready ? "等待登录" : "查询分析";
  const analysisTone = status.query_ready ? "query-ready" : !status.environment_ready ? "env-check" : "pending";
  const analysisDescription = status.query_ready
    ? "将按以下配置执行查询"
    : !status.environment_ready
      ? "先确认 ChromeDriver、浏览器和本机依赖"
      : nextAction.description;
  const riskText = riskLabel[status.risk_level] ?? "未知风险";
  const autoSubmitEnabled = status.auto_submit_enabled || config.auto_submit;
  const autoAlternateEnabled = status.auto_alternate_enabled || config.auto_alternate;

  const goToMonitor = () => setActivePage("购票监控");

  return (
    <div className="rail-dashboard" aria-label="RailWatch 仪表盘">
      <section className="journey-strip" aria-label="当前行程">
        <div className="journey-route">
          <span>当前行程</span>
          <strong>
            {fromStation.replace("南", "")} <span>→</span> {toStation.replace("虹桥", "")}
          </strong>
        </div>
        <div className="journey-meta">
          <article>
            <CalendarDays size={16} />
            <span>出发日期</span>
            <strong>{tripDate}</strong>
          </article>
          <article>
            <TrainFront size={16} />
            <span>车次偏好</span>
            <strong>{trainFamily}</strong>
          </article>
          <article>
            <UserRound size={16} />
            <span>席别偏好</span>
            <strong>{seatPreference}</strong>
          </article>
        </div>
      </section>

      <section className="dispatch-timeline" aria-label="监控流程">
        <ol className="workflow-stepper screenshot-stepper" aria-label="监控流程">
          {workflowSteps.map((step) => {
            const Icon = step.icon;
            const done = step.state === "done";
            return (
              <li className={`screenshot-step ${step.state}`} key={step.label} aria-current={step.state === "current" ? "step" : undefined}>
                <span className="step-node">
                  <Icon size={18} />
                  {done ? (
                    <span className="step-check">
                      <Check size={11} />
                    </span>
                  ) : null}
                </span>
                <strong>{step.label}</strong>
                <small>{step.description || workflowShortText[step.state]}</small>
              </li>
            );
          })}
        </ol>
      </section>

      <div className="dashboard-panels">
        <section className="dashboard-panel trip-overview">
          <h2>行程概览</h2>
          <dl className="snapshot-list">
            <dt>出发站</dt>
            <dd>{fromStation}</dd>
            <dt>到达站</dt>
            <dd>{toStation}</dd>
            <dt>出发日期</dt>
            <dd>{tripDate}</dd>
            <dt>车次偏好</dt>
            <dd>{trainPreference}</dd>
            <dt>席别偏好</dt>
            <dd>{seatPreference}</dd>
            <dt>乘客</dt>
            <dd>{passengerText}</dd>
          </dl>
          <Button block size="small" onClick={() => setActivePage("行程设置")}>
            查看 / 编辑行程
          </Button>
        </section>

        <section className="dashboard-panel query-analysis">
          <h2>查询分析</h2>
          <div className="analysis-body">
            <div className="analysis-head">
              <div className={`analysis-orb ${analysisTone}`} aria-hidden="true">
                <Radar size={24} />
              </div>
              <div className={`analysis-copy ${analysisTone}`}>
                <strong className="analysis-status">{analysisTitle}</strong>
                <p>{analysisDescription}</p>
              </div>
            </div>
            <dl className="analysis-grid">
            <div>
              <dt>站点范围</dt>
              <dd>
                {fromStation} → {toStation}
              </dd>
            </div>
            <div>
              <dt>日期范围</dt>
              <dd>{compactTripDate}（±3天）</dd>
            </div>
            <div>
              <dt>车次偏好</dt>
              <dd>{trainPreference}</dd>
            </div>
            <div>
              <dt>席别偏好</dt>
              <dd>{seatPreference}</dd>
            </div>
            </dl>
          </div>
        </section>
      </div>

      <section className="dashboard-panel monitor-card">
        <div className="monitor-primary">
          <div className="monitor-icon">
            <Radar size={22} />
          </div>
          <div>
            <h2>{status.monitoring ? "监控运行中" : "监控未运行"}</h2>
            <p>{status.monitoring ? "正在按配置刷新查询结果" : "就绪后可启动监控"}</p>
          </div>
        </div>
        <div className="monitor-settings">
          <label>
            <span>请求模式</span>
            <SegmentedControl
              ariaLabel="请求模式"
              options={["快速模式", "均衡模式", "保守模式"] as const}
              value={smartRateToRequestMode(config.smart_rate, config.interval)}
              onChange={(next: RequestMode) => {
                const patch: Partial<RailWatchConfig> = { smart_rate: requestModeToSmartRate(next) };
                if (next === "快速模式") {
                  patch.interval = Math.min(config.interval, 3);
                } else if (next === "均衡模式") {
                  patch.interval = Math.max(4, Math.min(config.interval, 5));
                } else {
                  patch.interval = Math.max(config.interval, 6);
                }
                setConfig(patch);
              }}
            />
          </label>
          <label>
            <span>并发请求</span>
            <span className="stepper-control">
              <button type="button" aria-label="减少并发">
                -
              </button>
              <strong>3</strong>
              <button type="button" aria-label="增加并发">
                +
              </button>
            </span>
          </label>
          <Button className="monitor-page-button" icon={<MonitorPlay size={14} />} onClick={goToMonitor} type="primary">
            进入购票监控
          </Button>
        </div>
        <div className="monitor-metrics">
          <span>
            <Clock3 size={13} />
            <em>下次查询</em>
            <strong>{status.monitoring ? `${config.interval} 秒` : "-"}</strong>
          </span>
          <span>
            <Pause size={13} />
            <em>已运行时间</em>
            <strong>{status.monitoring ? "00:12" : "-"}</strong>
          </span>
          <span>
            <Search size={13} />
            <em>请求次数</em>
            <strong>0</strong>
          </span>
          <span>
            <Bell size={13} />
            <em>命中记录</em>
            <strong>{hits.length}</strong>
          </span>
          <span>
            <Check size={13} />
            <em>成功提交</em>
            <strong>0</strong>
          </span>
        </div>
      </section>

      <section className={`dashboard-panel automation-panel ${riskTone}`}>
        <div className="automation-lock">
          <Lock size={20} />
        </div>
        <div className="automation-copy">
          <div className="automation-title-row">
            <h2>危险自动化（已锁定）</h2>
            <span>{riskText}</span>
          </div>
          <p>为保障账号安全，自动提交等危险操作默认关闭。</p>
          <div className="automation-flags" aria-label="自动化状态">
            <label className="automation-toggle">
              <Switch checked={autoSubmitEnabled} disabled size="small" />
              <span>
                自动提交购票 <strong>{autoSubmitEnabled ? "已启用" : "未启用"}</strong>
              </span>
            </label>
            <label className="automation-toggle">
              <Switch checked={false} disabled size="small" />
              <span>
                自动跳转支付 <strong>未启用</strong>
              </span>
            </label>
            <label className="automation-toggle">
              <Switch checked={autoAlternateEnabled} disabled size="small" />
              <span>
                自动候补下单 <strong>{autoAlternateEnabled ? "已启用" : "未启用"}</strong>
              </span>
            </label>
          </div>
        </div>
        <div className="automation-actions">
          <Button icon={<Lock size={13} />} onClick={() => setActivePage("系统设置")} size="small">
            解锁并配置
          </Button>
          <small>启用前需二次确认</small>
        </div>
        <div className="automation-warning">
          <ShieldAlert size={14} />
          <span>启用后可能导致账号受限或封禁，请充分了解风险后谨慎操作。</span>
          <button type="button">了解更多风险说明</button>
        </div>
      </section>
    </div>
  );
}
