import { useMemo, useState } from "react";
import { Button, Input, Select, Switch } from "antd";
import {
  ArrowLeftRight,
  BarChart3,
  Building2,
  CalendarDays,
  CircleHelp,
  FolderOpen,
  Plus,
  Save,
  TrainFront,
  X,
} from "lucide-react";
import { useRailWatchStore } from "../store/useRailWatchStore";
import {
  executionReference,
  getDateRangeStatus,
  getTripDateStatus,
  todayIso,
  useBeijingToday,
} from "../lib/tripDate";
import type { RailWatchConfig } from "../types";
import type { CommandRunner, ConfirmDialog } from "./componentTypes";
import { PreferenceSection } from "./PreferenceSection";
import { RiskToggle } from "./DisplayPrimitives";
import {
  PRIORITIES, REQUEST_MODES, delayPreview, isStrategyCustomized, modeDefaults,
  priorityDefaults, queryPriority, requestMode as getRequestMode,
  type QueryPriority, type RequestMode,
} from "../lib/queryStrategy";

type DateRangePreset = "单日" | "±1天" | "±2天";

const SEAT_OPTIONS = ["不限", "二等座", "一等座", "商务座"] as const;
const COMMON_TRAINS = ["G1", "G3", "G17", "D313", "D321"];

function NumberStepper({
  ariaLabel,
  decimals = 0,
  max,
  min,
  onChange,
  step,
  suffix,
  value,
}: {
  ariaLabel: string;
  decimals?: number;
  max: number;
  min: number;
  onChange: (value: number) => void;
  step: number;
  suffix?: string;
  value: number;
}) {
  const formatValue = (next: number) =>
    decimals > 0 ? next.toFixed(decimals) : String(next);

  const adjust = (delta: number) => {
    const next = Math.min(
      max,
      Math.max(min, Number((value + delta).toFixed(decimals))),
    );
    onChange(next);
  };

  return (
    <div className="trip-stepper-field">
      <span className="stepper-control" aria-label={ariaLabel}>
        <button
          aria-label={`减少${ariaLabel}`}
          onClick={() => adjust(-step)}
          type="button"
        >
          -
        </button>
        <strong>{formatValue(value)}</strong>
        <button
          aria-label={`增加${ariaLabel}`}
          onClick={() => adjust(step)}
          type="button"
        >
          +
        </button>
      </span>
      {suffix ? <span className="trip-stepper-suffix">{suffix}</span> : null}
    </div>
  );
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
          className={
            value === option ? "segmented-option active" : "segmented-option"
          }
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

function parsePassengers(value: string) {
  return value
    .split(/[,，、]/)
    .map((name) => name.trim())
    .filter(Boolean);
}

function formatPassengers(names: string[]) {
  return names.join("，");
}

export function TripSetupPage({
  busy,
  confirm,
  runCommand,
}: {
  busy: string | null;
  confirm: ConfirmDialog;
  runCommand: CommandRunner;
}) {
  const config = useRailWatchStore((state) => state.config);
  const setConfig = useRailWatchStore((state) => state.setConfig);
  const [dateRange, setDateRange] = useState<DateRangePreset>(
    () => (config.date_range as DateRangePreset) || "±1天",
  );
  const priority = queryPriority(config);
  const requestMode = getRequestMode(config);
  const preview = delayPreview(config);
  const customized = isStrategyCustomized(config);
  const [passengerDraft, setPassengerDraft] = useState("");

  const update = (patch: Partial<RailWatchConfig>) => setConfig(patch);
  const today = useBeijingToday();
  const windowDays = useRailWatchStore(
    (state) => state.runtime.date_policy?.presale_window_days,
  );
  const monitoring = useRailWatchStore((state) => state.status.monitoring);
  const tripDateStatus = getTripDateStatus(config.date, today, windowDays);
  const rangeStatus = getDateRangeStatus(
    config.date,
    config.date_range,
    executionReference(config, today),
    windowDays,
  );
  const passengerNames = useMemo(
    () => parsePassengers(config.passengers),
    [config.passengers],
  );
  const selectedSeats = useMemo(() => {
    if (!config.seat_keyword.trim()) {
      return ["不限"];
    }
    return config.seat_keyword
      .split(/[,，、]/)
      .map((seat) => seat.trim())
      .filter(Boolean);
  }, [config.seat_keyword]);

  const guardedAutomation = async (
    key: "auto_submit" | "auto_alternate",
    checked: boolean,
  ) => {
    if (!checked) {
      update({ [key]: false });
      return;
    }
    const accepted = await confirm(
      key === "auto_submit" ? "启用自动提交" : "启用自动候补",
      key === "auto_submit"
        ? "自动提交可在发现车票后自动进入订单流程。请确认是否继续。"
        : "自动候补可在无票时自动提交候补订单。请确认是否继续。",
    );
    update({ [key]: accepted });
  };

  const swapStations = () => {
    update({
      from_station_cn: config.to_station_cn,
      to_station_cn: config.from_station_cn,
    });
  };

  const toggleSeat = (seat: (typeof SEAT_OPTIONS)[number]) => {
    if (seat === "不限") {
      update({ seat_keyword: "" });
      return;
    }

    if (selectedSeats.includes("不限")) {
      update({ seat_keyword: seat });
      return;
    }

    if (selectedSeats.includes(seat)) {
      const filtered = selectedSeats.filter((item) => item !== seat);
      update({ seat_keyword: filtered.length ? filtered.join("，") : "" });
      return;
    }

    update({ seat_keyword: [...selectedSeats, seat].join("，") });
  };

  const addPassenger = () => {
    const name = passengerDraft.trim();
    if (!name) {
      return;
    }
    const nextNames = [...passengerNames, name];
    update({
      passengers: formatPassengers(nextNames),
      passenger_count: Math.max(1, nextNames.length),
    });
    setPassengerDraft("");
  };

  const removePassenger = (name: string) => {
    const nextNames = passengerNames.filter((item) => item !== name);
    update({
      passengers: formatPassengers(nextNames),
      passenger_count: Math.max(1, nextNames.length || 1),
    });
  };

  const applyCommonTrain = () => {
    const current = config.train_code
      .split(/[,，、\s]+/)
      .map((code) => code.trim())
      .filter(Boolean);
    const merged = [...new Set([...current, ...COMMON_TRAINS])];
    update({ train_code: merged.join(", ") });
  };

  const handlePriorityChange = (next: string) => {
    const key = (Object.keys(PRIORITIES) as QueryPriority[]).find((key) => PRIORITIES[key].label === next);
    if (key) update(priorityDefaults(key));
  };

  const handleRequestModeChange = (next: RequestMode) => {
    update(modeDefaults(next));
  };

  const loadConfig = async () => {
    const loaded = await runCommand<RailWatchConfig>("loadConfig");
    if (loaded) {
      setConfig(loaded);
      setDateRange((loaded.date_range as DateRangePreset) || "±1天");
    }
  };

  const saveConfig = async () => {
    if (tripDateStatus.expired) {
      const accepted = await confirm(
        "出发日期已过期",
        `保存的出发日期（${config.date}）早于今天，执行时将跳过无效日期。是否仍要保存？`,
      );
      if (!accepted) {
        return;
      }
    }
    await runCommand("saveConfig", { config }, "设置已保存");
  };

  return (
    <div className="trip-setup-workspace">
      <section className="trip-setup-card">
        <header className="trip-setup-head">
          <div>
            <span className="eyebrow">行程偏好</span>
            <p>
              {monitoring
                ? "运行中的行程保持不变，修改将在下次运行生效"
                : "配置查询条件与监控策略"}
            </p>
          </div>
          <Button
            className="trip-load-button"
            icon={<FolderOpen size={15} />}
            loading={busy === "loadConfig"}
            onClick={() => void loadConfig()}
          >
            恢复上次保存
          </Button>
        </header>

        <div className="trip-setup-form-scroll">
          <PreferenceSection
            id="trip-basics"
            title="路线与乘客"
            description="确定你的目的地与同行人"
            defaultOpen
          >
            <div className="trip-form-row trip-form-row--stations">
              <label className="trip-field">
                <span>出发站</span>
                <span className="trip-input-shell">
                  <Building2 size={15} />
                  <Input
                    aria-label="出发站"
                    bordered={false}
                    value={config.from_station_cn}
                    onChange={(event) =>
                      update({ from_station_cn: event.target.value })
                    }
                  />
                </span>
              </label>
              <button
                aria-label="交换出发站与到达站"
                className="trip-swap-button"
                onClick={swapStations}
                type="button"
              >
                <ArrowLeftRight size={16} />
              </button>
              <label className="trip-field">
                <span>到达站</span>
                <span className="trip-input-shell">
                  <Building2 size={15} />
                  <Input
                    aria-label="到达站"
                    bordered={false}
                    value={config.to_station_cn}
                    onChange={(event) =>
                      update({ to_station_cn: event.target.value })
                    }
                  />
                </span>
              </label>
            </div>

            <div className="trip-form-row trip-form-row--split">
              <label className="trip-field">
                <span>出发日期</span>
                <span className="trip-input-shell">
                  <CalendarDays size={15} />
                  <input
                    aria-label="出发日期"
                    className="native-input trip-native-input"
                    type="date"
                    min={todayIso(today)}
                    value={config.date}
                    onChange={(event) => update({ date: event.target.value })}
                  />
                </span>
                {tripDateStatus.warning ? (
                  <small className="trip-date-hint">
                    {tripDateStatus.warning}
                  </small>
                ) : null}
                <small className="trip-date-hint">
                  {rangeStatus.invalid
                    ? "请输入有效日期"
                    : `实际执行日期：${rangeStatus.valid.join("、") || "无"}${rangeStatus.skipped.length ? `；跳过：${rangeStatus.skipped.join("、")}` : ""}`}
                </small>
              </label>
              <div className="trip-field">
                <span>日期范围</span>
                <SegmentedControl
                  ariaLabel="日期范围"
                  options={["单日", "±1天", "±2天"] as const}
                  value={dateRange}
                  onChange={(next) => {
                    setDateRange(next);
                    update({ date_range: next });
                  }}
                />
              </div>
            </div>

            <div className="trip-form-row trip-form-row--split">
              <label className="trip-field">
                <span>车次（可多选）</span>
                <span className="trip-input-with-action">
                  <span className="trip-input-shell">
                    <TrainFront size={15} />
                    <Input
                      aria-label="车次"
                      bordered={false}
                      placeholder="如：G1, G2, D3 或留空"
                      value={config.train_code}
                      onChange={(event) =>
                        update({ train_code: event.target.value.toUpperCase() })
                      }
                    />
                  </span>
                  <Button
                    className="trip-inline-button"
                    onClick={applyCommonTrain}
                    type="default"
                  >
                    常用车次
                  </Button>
                </span>
              </label>
              <div className="trip-field">
                <span>席别（可多选）</span>
                <div aria-label="席别" className="chip-group" role="group">
                  {SEAT_OPTIONS.map((seat) => (
                    <button
                      aria-pressed={selectedSeats.includes(seat)}
                      className={
                        selectedSeats.includes(seat)
                          ? "chip-option active"
                          : "chip-option"
                      }
                      key={seat}
                      onClick={() => toggleSeat(seat)}
                      type="button"
                    >
                      {seat}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="trip-form-row trip-form-row--split">
              <div className="trip-field">
                <span>乘客</span>
                <div className="passenger-strip">
                  {passengerNames.map((name) => (
                    <span className="passenger-tag" key={name}>
                      {name} 成人
                      <button
                        aria-label={`移除乘客 ${name}`}
                        onClick={() => removePassenger(name)}
                        type="button"
                      >
                        <X size={12} />
                      </button>
                    </span>
                  ))}
                  <span className="passenger-add">
                    <input
                      aria-label="添加乘客"
                      placeholder="姓名"
                      value={passengerDraft}
                      onChange={(event) =>
                        setPassengerDraft(event.target.value)
                      }
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          addPassenger();
                        }
                      }}
                    />
                    <button
                      aria-label="添加乘客"
                      onClick={addPassenger}
                      type="button"
                    >
                      <Plus size={14} />
                      添加乘客
                    </button>
                  </span>
                </div>
              </div>
            </div>
          </PreferenceSection>
          <PreferenceSection
            id="trip-query"
            title="查询策略"
            description="调整查询频率、优先级与座位偏好"
          >
            <div className="trip-form-row trip-form-row--split">
              {" "}
              <div className="trip-field">
                <span className="trip-field-label-with-help">
                  优先级
                  <CircleHelp aria-hidden size={13} />
                </span>
                <SegmentedControl
                  ariaLabel="优先级"
                  options={["速度优先", "成功率优先"] as const}
                  value={PRIORITIES[priority].label}
                  onChange={handlePriorityChange}
                />
                <small className="field-help">
                  {customized ? "已自定义；再次选择优先级可恢复推荐参数。" : "已应用推荐参数，可继续手动调整。"}
                  {priority === "speed"
                    ? "速度优先缩短查询等待，适合关注起售后的及时响应。"
                    : "成功率优先侧重稳定查询和较长等待，适合持续监控；不代表购票成功率保证。"}
                </small>
              </div>{" "}
              <label className="trip-field">
                <span>座位偏好</span>
                <Select
                  aria-label="座位偏好"
                  className="trip-select"
                  options={["无偏好", "靠窗优先", "靠过道优先"].map(
                    (value) => ({ value, label: value }),
                  )}
                  value={config.seat_prefer}
                  onChange={(value) => update({ seat_prefer: value })}
                />
              </label>
            </div>{" "}
            <div className="trip-form-row trip-form-row--quad">
              <div className="trip-field">
                <span>查询间隔</span>
                <NumberStepper
                  ariaLabel="查询间隔"
                  decimals={1}
                  max={60}
                  min={config.smart_rate ? REQUEST_MODES[requestMode].min_interval : 1}
                  step={0.5}
                  suffix="秒"
                  value={config.interval}
                  onChange={(value) => update({ interval: value })}
                />
              </div>
              <div className="trip-field">
                <span>超时时间</span>
                <NumberStepper
                  ariaLabel="超时时间"
                  max={120}
                  min={5}
                  step={1}
                  suffix="秒"
                  value={config.query_timeout}
                  onChange={(value) => update({ query_timeout: value })}
                />
              </div>
              <div className="trip-field">
                <span className="trip-field-label-with-help">
                  随机延迟
                  <CircleHelp aria-hidden size={13} />
                </span>
                <div className="trip-readonly-pill">
                  {preview.label} 秒
                </div>
                <small className="field-help">{preview.detail}</small>
              </div>
              <div className="trip-field">
                <span className="trip-field-label-with-help">
                  请求模式
                  <CircleHelp aria-hidden size={13} />
                </span>
                <Select
                  aria-label="请求模式"
                  className="trip-select"
                  options={(Object.keys(REQUEST_MODES) as RequestMode[])
                    .filter((mode) => mode !== "legacy" || requestMode === "legacy")
                    .map((mode) => ({ value: mode, label: REQUEST_MODES[mode].label }))}
                  value={requestMode}
                  onChange={(value) =>
                    handleRequestModeChange(value as RequestMode)
                  }
                />
              </div>
            </div>
            <div className="trip-advanced-switches">
              {" "}
              <label className="switch-row">
                <Switch
                  aria-label="保持会话"
                  checked={config.keep_alive}
                  onChange={(checked) => update({ keep_alive: checked })}
                />
                <span>保持会话</span>
              </label>
              <label className="switch-row">
                <Switch
                  aria-label="智能轮询"
                  checked={config.smart_rate}
                  onChange={(checked) => update({ smart_rate: checked })}
                />
                <span>智能轮询</span>
              </label>
            </div>
          </PreferenceSection>
          <PreferenceSection
            id="trip-timer"
            title="定时启动"
            description={
              config.timer_enabled
                ? "已启用 · 按北京时间等待起售"
                : "在指定的起售时间开始监控"
            }
            enabled={config.timer_enabled}
          >
            <label className="switch-row">
              <Switch
                aria-label="定时启动"
                checked={config.timer_enabled}
                onChange={(checked) => update({ timer_enabled: checked })}
              />
              <span>启用定时启动</span>
            </label>
            <label className="trip-field">
              <span>起售日期时间（北京时间）</span>
              <input
                aria-label="定时启动时间"
                className="native-input"
                type="datetime-local"
                step="1"
                value={config.sale_at?.replace(/\+08:00$/, "") || ""}
                onChange={(event) =>
                  update({
                    sale_at: event.target.value
                      ? `${event.target.value}+08:00`
                      : "",
                    target_time: event.target.value.slice(11),
                    sale_time_source: "manual",
                    sale_time_checked_at: new Date().toISOString(),
                  })
                }
              />
            </label>
            <p>
              请按 12306
              公布的车站起售时间核对日期，并提前完成登录及人证核验。定时使用系统时钟，请提前校准电脑时间；起售前
              10 秒不再启动准备操作。
            </p>
            <p>旧版时间 {config.target_time} 不会自动顺延至次日。</p>
          </PreferenceSection>
          <PreferenceSection
            id="trip-automation"
            title="自动化"
            description={
              config.auto_submit || config.auto_alternate
                ? "已启用 · 核验与支付需人工完成"
                : "自动提交与自动候补默认关闭"
            }
            enabled={config.auto_submit || config.auto_alternate}
          >
            <label className="trip-field">
              <span>候补截止</span>
              <input
                aria-label="候补截止"
                className="native-input"
                type="text"
                placeholder="开车前60分钟，或 2026-09-10 18:00"
                value={config.alternate_deadline}
                onChange={(event) =>
                  update({ alternate_deadline: event.target.value })
                }
              />
            </label>
            <p>
              候补截止可填“开车前60分钟”或完整日期时间，仅选择官方页面提供的对应选项。
            </p>{" "}
            <div className="trip-advanced-risk">
              <RiskToggle
                checked={config.auto_submit}
                title={config.auto_submit ? "自动提交已启用" : "自动提交关闭"}
                description="开启时需要确认；开启后命中车票可能自动进入订单流程。"
                onChange={(checked) =>
                  void guardedAutomation("auto_submit", checked)
                }
              />
              <RiskToggle
                checked={config.auto_alternate}
                title={
                  config.auto_alternate ? "候补排队已启用" : "候补排队关闭"
                }
                description="按已配置的乘车人和席别提交首选候补；人工支付预付款后才生效。实验性功能，需核对官方订单。"
                onChange={(checked) =>
                  void guardedAutomation("auto_alternate", checked)
                }
              />
            </div>
          </PreferenceSection>
        </div>
        <footer className="trip-setup-footer">
          <Button
            icon={<Save size={15} />}
            loading={busy === "saveConfig"}
            onClick={() => void saveConfig()}
          >
            保存配置
          </Button>
          <Button
            type="primary"
            icon={<BarChart3 size={15} />}
            loading={busy === "analyzeQuery"}
            onClick={() => void runCommand("analyzeQuery", { config })}
          >
            查询余票
          </Button>
        </footer>
      </section>
    </div>
  );
}
