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
import type { RailWatchConfig } from "../types";
import type { CommandRunner, ConfirmDialog } from "./componentTypes";
import { RiskToggle } from "./DisplayPrimitives";

type DateRangePreset = "单日" | "±1天" | "±2天";
type PriorityMode = "速度优先" | "成功率优先";
type RequestMode = "均衡模式" | "保守模式" | "快速模式";

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
  const formatValue = (next: number) => (decimals > 0 ? next.toFixed(decimals) : String(next));

  const adjust = (delta: number) => {
    const next = Math.min(max, Math.max(min, Number((value + delta).toFixed(decimals))));
    onChange(next);
  };

  return (
    <div className="trip-stepper-field">
      <span className="stepper-control" aria-label={ariaLabel}>
        <button aria-label={`减少${ariaLabel}`} onClick={() => adjust(-step)} type="button">
          -
        </button>
        <strong>{formatValue(value)}</strong>
        <button aria-label={`增加${ariaLabel}`} onClick={() => adjust(step)} type="button">
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

function parsePassengers(value: string) {
  return value
    .split(/[,，、]/)
    .map((name) => name.trim())
    .filter(Boolean);
}

function formatPassengers(names: string[]) {
  return names.join("，");
}

function getRandomDelayLabel(interval: number) {
  const low = Math.max(1, interval * 0.7);
  const high = Math.max(low + 0.1, interval * 1.3);
  return `${low.toFixed(1)} ~ ${high.toFixed(1)}`;
}

function requestModeToSmartRate(mode: RequestMode) {
  return mode !== "保守模式";
}

function smartRateToRequestMode(smartRate: boolean, interval: number): RequestMode {
  if (!smartRate) {
    return "保守模式";
  }
  return interval <= 3 ? "快速模式" : "均衡模式";
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
  const [dateRange, setDateRange] = useState<DateRangePreset>(() => (config.date_range as DateRangePreset) || "±1天");
  const [priority, setPriority] = useState<PriorityMode>(() => (config.smart_rate ? "速度优先" : "成功率优先"));
  const [requestMode, setRequestMode] = useState<RequestMode>(() => smartRateToRequestMode(config.smart_rate, config.interval));
  const [passengerDraft, setPassengerDraft] = useState("");

  const update = (patch: Partial<RailWatchConfig>) => setConfig(patch);
  const passengerNames = useMemo(() => parsePassengers(config.passengers), [config.passengers]);
  const selectedSeats = useMemo(() => {
    if (!config.seat_keyword.trim()) {
      return ["不限"];
    }
    return config.seat_keyword
      .split(/[,，、]/)
      .map((seat) => seat.trim())
      .filter(Boolean);
  }, [config.seat_keyword]);

  const guardedAutomation = async (key: "auto_submit" | "auto_alternate", checked: boolean) => {
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

  const handlePriorityChange = (next: PriorityMode) => {
    setPriority(next);
    if (next === "速度优先") {
      update({ smart_rate: true, interval: Math.min(config.interval, 4) });
      setRequestMode("快速模式");
      return;
    }
    update({ smart_rate: false, interval: Math.max(config.interval, 5) });
    setRequestMode("保守模式");
  };

  const handleRequestModeChange = (next: RequestMode) => {
    setRequestMode(next);
    update({ smart_rate: requestModeToSmartRate(next) });
    if (next === "快速模式") {
      update({ interval: Math.min(config.interval, 3) });
    }
    if (next === "均衡模式") {
      update({ interval: Math.max(4, Math.min(config.interval, 5)) });
    }
    if (next === "保守模式") {
      update({ interval: Math.max(config.interval, 6) });
    }
  };

  const loadConfig = async () => {
    const loaded = await runCommand<RailWatchConfig>("loadConfig");
    if (loaded) {
      setConfig(loaded);
      setRequestMode(smartRateToRequestMode(loaded.smart_rate, loaded.interval));
      setPriority(loaded.smart_rate ? "速度优先" : "成功率优先");
      setDateRange((loaded.date_range as DateRangePreset) || "±1天");
    }
  };

  return (
    <div className="trip-setup-workspace">
      <section className="trip-setup-card content-band">
        <header className="trip-setup-head">
          <div>
            <h2>行程设置</h2>
            <p>配置查询条件与监控策略</p>
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
          <div className="trip-setup-form">
          <div className="trip-setup-fields">
          <div className="trip-form-row trip-form-row--stations">
            <label className="trip-field">
              <span>出发站</span>
              <span className="trip-input-shell">
                <Building2 size={15} />
                <Input
                  aria-label="出发站"
                  bordered={false}
                  value={config.from_station_cn}
                  onChange={(event) => update({ from_station_cn: event.target.value })}
                />
              </span>
            </label>
            <button aria-label="交换出发站与到达站" className="trip-swap-button" onClick={swapStations} type="button">
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
                  onChange={(event) => update({ to_station_cn: event.target.value })}
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
                  value={config.date}
                  onChange={(event) => update({ date: event.target.value })}
                />
              </span>
            </label>
            <div className="trip-field">
              <span>日期范围</span>
              <SegmentedControl
                ariaLabel="日期范围"
                options={["单日", "±1天", "±2天"] as const}
                value={dateRange}
                onChange={(next) => { setDateRange(next); update({ date_range: next }); }}
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
                    onChange={(event) => update({ train_code: event.target.value.toUpperCase() })}
                  />
                </span>
                <Button className="trip-inline-button" onClick={applyCommonTrain} type="default">
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
                    className={selectedSeats.includes(seat) ? "chip-option active" : "chip-option"}
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
                    <button aria-label={`移除乘客 ${name}`} onClick={() => removePassenger(name)} type="button">
                      <X size={12} />
                    </button>
                  </span>
                ))}
                <span className="passenger-add">
                  <input
                    aria-label="添加乘客"
                    placeholder="姓名"
                    value={passengerDraft}
                    onChange={(event) => setPassengerDraft(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.preventDefault();
                        addPassenger();
                      }
                    }}
                  />
                  <button aria-label="添加乘客" onClick={addPassenger} type="button">
                    <Plus size={14} />
                    添加乘客
                  </button>
                </span>
              </div>
            </div>
            <div className="trip-field">
              <span className="trip-field-label-with-help">
                优先级
                <CircleHelp aria-hidden size={13} />
              </span>
              <SegmentedControl
                ariaLabel="优先级"
                options={["速度优先", "成功率优先"] as const}
                value={priority}
                onChange={handlePriorityChange}
              />
            </div>
          </div>

          <div className="trip-form-row trip-form-row--quad">
            <div className="trip-field">
              <span>查询间隔</span>
              <NumberStepper
                ariaLabel="查询间隔"
                decimals={1}
                max={60}
                min={1}
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
              <div className="trip-readonly-pill">{getRandomDelayLabel(config.interval)} 秒</div>
            </div>
            <div className="trip-field">
              <span className="trip-field-label-with-help">
                请求模式
                <CircleHelp aria-hidden size={13} />
              </span>
              <Select
                aria-label="请求模式"
                className="trip-select"
                options={[
                  { value: "均衡模式", label: "均衡模式" },
                  { value: "保守模式", label: "保守模式" },
                  { value: "快速模式", label: "快速模式" },
                ]}
                value={requestMode}
                onChange={(value) => handleRequestModeChange(value as RequestMode)}
              />
            </div>
          </div>
          </div>

          <div className="trip-advanced">
            <div className="trip-advanced-head">
              <strong>高级选项</strong>
              <small>更多过滤条件与策略</small>
            </div>
            <div className="trip-advanced-body">
                <div className="trip-advanced-grid">
                  <label className="trip-field">
                    <span>座位偏好</span>
                    <Select
                      aria-label="座位偏好"
                      className="trip-select"
                      options={["无偏好", "靠窗优先", "靠过道优先"].map((value) => ({ value, label: value }))}
                      value={config.seat_prefer}
                      onChange={(value) => update({ seat_prefer: value })}
                    />
                  </label>
                  <label className="trip-field">
                    <span>预备秒数</span>
                    <NumberStepper
                      ariaLabel="预备秒数"
                      max={30}
                      min={0}
                      step={1}
                      suffix="秒"
                      value={config.prepare_time}
                      onChange={(value) => update({ prepare_time: value })}
                    />
                  </label>
                  <label className="trip-field">
                    <span>候补截止</span>
                    <input
                      aria-label="候补截止"
                      className="native-input"
                      type="time"
                      value={config.alternate_deadline}
                      onChange={(event) => update({ alternate_deadline: event.target.value })}
                    />
                  </label>
                  <label className="trip-field">
                    <span>定时启动</span>
                    <input
                      aria-label="定时启动时间"
                      className="native-input"
                      type="time"
                      step="1"
                      value={config.target_time}
                      onChange={(event) => update({ target_time: event.target.value })}
                    />
                  </label>
                </div>
                <div className="trip-advanced-switches">
                  <label className="switch-row">
                    <Switch aria-label="定时启动" checked={config.timer_enabled} onChange={(checked) => update({ timer_enabled: checked })} />
                    <span>启用定时启动</span>
                  </label>
                  <label className="switch-row">
                    <Switch aria-label="保持会话" checked={config.keep_alive} onChange={(checked) => update({ keep_alive: checked })} />
                    <span>保持会话</span>
                  </label>
                  <label className="switch-row">
                    <Switch aria-label="智能轮询" checked={config.smart_rate} onChange={(checked) => update({ smart_rate: checked })} />
                    <span>智能轮询</span>
                  </label>
                </div>
                <div className="trip-advanced-risk">
                  <RiskToggle
                    checked={config.auto_submit}
                    title={config.auto_submit ? "自动提交已启用" : "自动提交关闭"}
                    description="开启时需要确认；开启后命中车票可能自动进入订单流程。"
                    onChange={(checked) => void guardedAutomation("auto_submit", checked)}
                  />
                  <RiskToggle
                    checked={config.auto_alternate}
                    title={config.auto_alternate ? "候补排队已启用" : "候补排队关闭"}
                    description="开启时需要确认；开启后无票时可能自动提交候补。"
                    onChange={(checked) => void guardedAutomation("auto_alternate", checked)}
                  />
                </div>
              </div>
          </div>
          </div>
        </div>

        <footer className="trip-setup-footer">
          <Button
            icon={<Save size={15} />}
            loading={busy === "saveConfig"}
            onClick={() => void runCommand("saveConfig", { config }, "设置已保存")}
          >
            保存配置
          </Button>
          <Button icon={<BarChart3 size={15} />} loading={busy === "analyzeQuery"} onClick={() => void runCommand("analyzeQuery", { config })}>
            查询余票
          </Button>
        </footer>
      </section>
    </div>
  );
}
