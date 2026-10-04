import { useEffect, useMemo, useState } from "react";
import { Alert, AutoComplete, Button, Input, InputNumber, Select, Switch } from "antd";
import { DATE_STRATEGIES, DATE_SCAN_BUDGET, dateStrategy, dateStrategySummary } from "../lib/dateStrategy";
import { ORDER_POLICY } from "../lib/orderPolicy";
import { automationConfigIssue } from "../lib/automationReadiness";
import {
  ArrowLeftRight,
  BarChart3,
  Building2,
  CalendarDays,
  ChevronDown,
  CircleHelp,
  FolderOpen,
  Plus,
  Save,
  TrainFront,
  X,
} from "lucide-react";
import { useRailWatchStore } from "../store/useRailWatchStore";
import { tripFingerprint } from "../store/railwatchStore";
import {
  executionReference,
  getDateRangeStatus,
  getTripDateStatus,
  todayIso,
  useBeijingToday,
} from "../lib/tripDate";
import type { PassengerCandidates, RailWatchConfig, StationSearchResult, StationSuggestion, TripChoices } from "../types";
import type { CommandRunner, ConfirmDialog } from "./componentTypes";
import { PreferenceSection } from "./PreferenceSection";
import { TimerSettings } from "./TimerSettings";
import { RiskToggle } from "./DisplayPrimitives";
import {
  PRIORITIES, REQUEST_MODES, delayPreview, isStrategyCustomized, modeDefaults,
  priorityDefaults, queryPriority, requestMode as getRequestMode,
  type QueryPriority, type RequestMode,
} from "../lib/queryStrategy";

type DateRangePreset = "单日" | "±1天" | "±2天";

const trainCodes = (value: string) => [...new Set(value.toUpperCase().split(/[,，、;；\s]+/).filter(Boolean))];

function StationField({ label, value, onChange, runCommand }: {
  label: string; value: string; onChange: (name: string) => void; runCommand: CommandRunner;
}) {
  const [items, setItems] = useState<StationSuggestion[]>([]);
  const [warning, setWarning] = useState<string | null>(null);
  const [focused, setFocused] = useState(false);
  const [searched, setSearched] = useState(false);
  useEffect(() => {
    const query = value.trim();
    if (!query) { setItems([]); setWarning(null); setSearched(false); return; }
    let current = true;
    setSearched(false);
    const timer = window.setTimeout(() => {
      void runCommand<StationSearchResult>("searchStations", { query, limit: 10 }).then(result => {
        if (!current) return;
        setItems(result?.items ?? []);
        setWarning(result?.warning ?? null);
        setSearched(Boolean(result));
      });
    }, 250);
    return () => { current = false; window.clearTimeout(timer); };
  }, [value, runCommand]);
  return <div className="trip-field">
    <label htmlFor={`station-${label}`}>{label}</label>
    <span className="trip-input-shell"><Building2 size={15} />
      <Input id={`station-${label}`} aria-label={label} bordered={false} value={value}
        onFocus={() => setFocused(true)} onBlur={() => window.setTimeout(() => setFocused(false), 150)}
        onChange={event => onChange(event.target.value)} />
    </span>
    {focused && items.length > 0 ? <div className="station-suggestions" role="listbox" aria-label={`${label}联想`}>
      {items.map(item => <button type="button" role="option" aria-selected={value === item.name}
        key={`${item.name}-${item.code}`} onMouseDown={event => event.preventDefault()}
        onClick={() => { onChange(item.name); setFocused(false); }}>
        {item.name}<small>{item.pinyin || item.code}</small>
      </button>)}
    </div> : null}
    {warning ? <small className="trip-date-hint" role="status">{warning}</small> : null}
    {!focused && searched && !warning && value.trim() && !items.some(item => item.name === value.trim())
      ? <small className="trip-date-hint" role="status">请从联想中选择完整站名；未匹配时请核对站码数据。</small> : null}
  </div>;
}

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
  const savedConfig = useRailWatchStore(state => state.savedConfig);
  const tripInitialized = useRailWatchStore(state => state.tripInitialized);
  const savedAt = useRailWatchStore(state => state.savedAt);
  const configSaveError = useRailWatchStore(state => state.configSaveError);
  const draftRead = useRailWatchStore(state => state.draftRead);
  const draftSaveState = useRailWatchStore(state => state.draftSaveState);
  const draftSavedAt = useRailWatchStore(state => state.draftSavedAt);
  const draftError = useRailWatchStore(state => state.draftError);
  const applyDraft = useRailWatchStore(state => state.applyDraft);
  const dismissDraft = useRailWatchStore(state => state.dismissDraft);
  const markConfigSaved = useRailWatchStore(state => state.markConfigSaved);
  const [dateRange, setDateRange] = useState<DateRangePreset>(
    () => (config.date_range as DateRangePreset) || "±1天",
  );
  useEffect(() => setDateRange((config.date_range as DateRangePreset) || "±1天"), [config.date_range]);
  const formalDirty = savedConfig ? tripFingerprint(config) !== tripFingerprint(savedConfig) : false;
  const formatSavedAt = (at: number | null) => at === null ? "未知" : new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  }).format(new Date(at * 1000));
  const priority = queryPriority(config);
  const requestMode = getRequestMode(config);
  const preview = delayPreview(config);
  const customized = isStrategyCustomized(config);
  const [passengerDraft, setPassengerDraft] = useState("");
  const [passengerError, setPassengerError] = useState("");
  const [passengerCandidates, setPassengerCandidates] = useState<PassengerCandidates | null>(null);
  const [readingPassengers, setReadingPassengers] = useState(false);
  const [choices, setChoices] = useState<TripChoices>({ recent_routes: [], favorites: [] });
  const [trainNotice, setTrainNotice] = useState("");
  const [stationRevision, setStationRevision] = useState(0);

  useEffect(() => {
    let current = true;
    void runCommand<TripChoices>("loadTripChoices").then(result => {
      if (current && result && Array.isArray(result.recent_routes) && Array.isArray(result.favorites)) setChoices(result);
    });
    return () => { current = false; };
  }, [runCommand]);

  const update = (patch: Partial<RailWatchConfig>) => setConfig(patch);
  const today = useBeijingToday();
  const windowDays = useRailWatchStore(
    (state) => state.runtime.date_policy?.presale_window_days,
  );
  const loadedSeatCapabilities = useRailWatchStore(state => state.runtime.seat_capabilities);
  const seatCapabilities = loadedSeatCapabilities ?? [];
  const automationIssue = automationConfigIssue(config, loadedSeatCapabilities);
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
  const selectedTrains = useMemo(() => trainCodes(config.train_code), [config.train_code]);
  const currentFavorite = choices.favorites.find(item => item.from_station === config.from_station_cn.trim() &&
    item.to_station === config.to_station_cn.trim());
  const setRoute = (from: string, to: string) => {
    if ((from !== config.from_station_cn || to !== config.to_station_cn) && selectedTrains.length) {
      setTrainNotice("路线已变化；现有目标车次会保留，请核对后再执行。此路线收藏不会自动应用。");
    }
    update({ from_station_cn: from, to_station_cn: to });
  };
  const moveTrain = (index: number, delta: number) => {
    const next = [...selectedTrains];
    const target = index + delta;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    update({ train_code: next.join(", ") });
  };
  const saveFavorites = async () => {
    const result = await runCommand<TripChoices>("saveTrainFavorites", {
      from_station: config.from_station_cn.trim(), to_station: config.to_station_cn.trim(), trains: selectedTrains,
    }, "当前路线的车次收藏已保存");
    if (result) setChoices(result);
  };

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
        ? "启用后将按设置的车次、日期、乘车人和席别自动提交订单，并自动点击官方弹窗的确认按钮；核验与支付仍需人工完成。"
        : "自动候补可在无票时自动提交候补订单。请确认是否继续。",
    );
    update({ [key]: accepted });
  };

  const swapStations = () => {
    setRoute(config.to_station_cn, config.from_station_cn);
  };

  const toggleSeat = (seat: string) => {
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
    if (!name) { setPassengerError("请输入乘客姓名。"); return; }
    if (name.length > 40 || /[,，、\r\n]/.test(name)) { setPassengerError("姓名格式无效，请输入单个完整姓名。"); return; }
    if (passengerNames.includes(name)) { setPassengerError("乘客姓名重复，请核对官方页面中的身份信息。"); return; }
    if (passengerNames.length >= 20) { setPassengerError("最多配置 20 位乘客。"); return; }
    const nextNames = [...passengerNames, name];
    update({
      passengers: formatPassengers(nextNames),
      passenger_count: Math.max(1, nextNames.length),
    });
    setPassengerDraft("");
    setPassengerError("");
  };

  const removePassenger = (index: number) => {
    const nextNames = passengerNames.filter((_, position) => position !== index);
    update({
      passengers: formatPassengers(nextNames),
      passenger_count: Math.max(1, nextNames.length || 1),
      passenger_selections: (config.passenger_selections ?? []).filter(item => item.name !== passengerNames[index]),
    });
  };

  const readPassengers = async () => {
    if (readingPassengers || busy || monitoring) return;
    setReadingPassengers(true);
    setPassengerCandidates(null);
    try {
      const result = await runCommand<PassengerCandidates>("readPassengers");
      setPassengerCandidates(result ?? { items: [], warning: "读取未完成，请检查浏览器状态后重试。" });
    } catch {
      setPassengerCandidates({ items: [], warning: "读取未完成，请检查浏览器状态后重试。" });
    } finally {
      setReadingPassengers(false);
    }
  };

  const addCandidate = (candidate: PassengerCandidates["items"][number]) => {
    if (candidate.ambiguous || candidate.ticket_type !== "adult" || passengerNames.includes(candidate.name)) return;
    if (passengerNames.length >= 20) { setPassengerError("最多配置 20 位乘客。"); return; }
    const next = [...passengerNames, candidate.name];
    update({ passengers: formatPassengers(next), passenger_count: next.length,
      passenger_selections: [...(config.passenger_selections ?? []), {
        name: candidate.name, ticket_type: candidate.ticket_type, identity_hint: candidate.identity_hint,
      }] });
    setPassengerError("");
  };

  const handlePriorityChange = (next: string) => {
    const key = (Object.keys(PRIORITIES) as QueryPriority[]).find((key) => PRIORITIES[key].label === next);
    if (key) update(priorityDefaults(key));
  };

  const handleRequestModeChange = (next: RequestMode) => {
    update(modeDefaults(next));
  };

  const loadConfig = async () => {
    if (formalDirty && !await confirm("恢复上次保存", "当前编辑尚未正式保存，恢复上次保存会覆盖这些修改。是否继续？")) return;
    const loaded = await runCommand<RailWatchConfig>("loadConfig");
    if (loaded) {
      setConfig(loaded);
      markConfigSaved(loaded, savedAt ?? Date.now() / 1000);
      setDateRange((loaded.date_range as DateRangePreset) || "±1天");
    }
  };

  const saveConfig = async () => {
    if (!tripInitialized) return;
    if (tripDateStatus.expired) {
      const accepted = await confirm(
        "出发日期已过期",
        `保存的出发日期（${config.date}）早于今天，执行时将跳过无效日期。是否仍要保存？`,
      );
      if (!accepted) {
        return;
      }
    }
    const result = await runCommand<RailWatchConfig>("saveConfig", { config }, "设置已保存");
    if (result) {
      const next = await runCommand<TripChoices>("loadTripChoices");
      if (next && Array.isArray(next.recent_routes) && Array.isArray(next.favorites)) setChoices(next);
    }
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
        <div className="trip-save-status" role="status">
          <span>{formalDirty ? "有未正式保存的修改" : "当前编辑与上次正式保存一致"}</span>
          <span>上次正式保存：{formatSavedAt(savedAt)}（北京时间）</span>
          <span>草稿：{draftSaveState === "editing" ? "编辑中" : draftSaveState === "saving" ? "保存中" :
            draftSaveState === "saved" ? `已保存 ${formatSavedAt(draftSavedAt)}` : draftSaveState === "error" ? "保存失败" :
            draftRead.status === "available" ? `发现可恢复草稿 ${formatSavedAt(draftRead.draft.saved_at)}` : "尚未保存"}</span>
          {!tripInitialized ? <span role="alert">已保存的行程尚未加载，暂不能保存配置，以免覆盖原配置。</span> : null}
          {configSaveError ? <span role="alert">正式保存失败：{configSaveError}</span> : null}
          {draftError ? <span role="alert">草稿：{draftError}</span> : null}
        </div>
        {draftRead.status === "available" ? <div className="trip-draft-recovery" role="group" aria-label="恢复行程草稿">
          <span>发现上次未正式保存的行程草稿（{formatSavedAt(draftRead.draft.saved_at)}）。恢复后不会启动监控。</span>
          <button type="button" onClick={applyDraft}>恢复草稿</button>
          <button type="button" onClick={dismissDraft}>使用已保存配置</button>
        </div> : null}
        {draftRead.status === "invalid" ? <div className="trip-draft-recovery" role="alert">{draftRead.warning}</div> : null}

        <div className="trip-setup-form-scroll">
          <PreferenceSection
            id="trip-basics"
            title="路线与乘客"
            description="确定你的目的地与同行人"
            defaultOpen
          >
            {automationIssue ? <Alert type="warning" showIcon message="自动化配置待完善" description={automationIssue} /> : null}
            <div className="trip-form-row trip-form-row--stations">
              <StationField key={`from-${stationRevision}`} label="出发站" value={config.from_station_cn} runCommand={runCommand}
                onChange={value => setRoute(value, config.to_station_cn)} />
              <button
                aria-label="交换出发站与到达站"
                className="trip-swap-button"
                onClick={swapStations}
                type="button"
              >
                <ArrowLeftRight size={16} />
              </button>
              <StationField key={`to-${stationRevision}`} label="到达站" value={config.to_station_cn} runCommand={runCommand}
                onChange={value => setRoute(config.from_station_cn, value)} />
            </div>
            {config.from_station_cn.trim() && config.from_station_cn.trim() === config.to_station_cn.trim()
              ? <small className="trip-date-hint" role="alert">出发站和到达站不能相同</small> : null}
            {trainNotice ? <small className="trip-date-hint" role="status">{trainNotice}</small> : null}
            <button type="button" className="trip-station-refresh" onClick={() => void runCommand("refreshStations", {}, "站码数据已更新").then(result => {
              if (result) setStationRevision(value => value + 1);
            })}>更新站码数据</button>
            {choices.recent_routes.length ? <div className="trip-route-choices" aria-label="最近路线">
              <span>最近路线：</span>{choices.recent_routes.map(route => <button type="button"
                key={`${route.from_station}-${route.to_station}`} onClick={() => setRoute(route.from_station, route.to_station)}>
                {route.from_station} → {route.to_station}
              </button>)}
            </div> : null}

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
              <div className="trip-field">
                <span>多日期策略</span>
                <Select aria-label="多日期策略" className="trip-select" value={dateStrategy(config)}
                  disabled={dateRange === "单日"}
                  options={Object.entries(DATE_STRATEGIES).map(([value, policy]) => ({ value, label: policy.label }))}
                  onChange={value => update({ date_strategy: value })} />
                <small className="field-help">{dateStrategySummary(config)}</small>
              </div>
              {dateStrategy(config) === "inventory_first" && dateRange !== "单日" ? <label className="trip-field">
                <span>跨日期扫描预算（秒）</span>
                <InputNumber aria-label="跨日期扫描预算（秒）" className="trip-select"
                  min={DATE_SCAN_BUDGET.min_budget_seconds} max={DATE_SCAN_BUDGET.max_budget_seconds} precision={0}
                  value={config.date_scan_budget_seconds ?? DATE_SCAN_BUDGET.scan_budget_seconds}
                  onChange={value => { if (value !== null) update({ date_scan_budget_seconds: value }); }} />
                <small className="field-help">扫描结束后仍会重新确认候补；{config.alternate_mode === "multiple" ? "按自动化设置添加并核对备选组合。" : "仅提交一个已核对的组合。"}</small>
              </label> : null}
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
                  <Button className="trip-inline-button" onClick={() => void saveFavorites()} type="default">
                    保存为本路线收藏
                  </Button>
                </span>
                {currentFavorite?.trains.length ? <span className="trip-route-choices">
                  本路线收藏：<button type="button" onClick={() => update({ train_code: currentFavorite.trains.join(", ") })}>
                    应用 {currentFavorite.trains.join("、")}
                  </button>
                </span> : null}
                {selectedTrains.length ? <span className="trip-train-order" aria-label="车次优先顺序">
                  {selectedTrains.map((code, index) => <span key={code}>
                    {index + 1}. {code}
                    <button type="button" aria-label={`上移 ${code}`} disabled={index === 0} onClick={() => moveTrain(index, -1)}>↑</button>
                    <button type="button" aria-label={`下移 ${code}`} disabled={index === selectedTrains.length - 1} onClick={() => moveTrain(index, 1)}>↓</button>
                  </span>)}
                </span> : null}
                <small className="field-help">查询本路线全部车次后，可在结果页按日期和实际区间选择目标。</small>
              </label>
              <div className="trip-field">
                <span>席别（可多选）</span>
                <div aria-label="席别" className="chip-group" role="group">
                  {[{ name: "不限", query: true, regular: false, alternate: false }, ...seatCapabilities.filter(seat => seat.query)].map((capability) => {
                    const seat = capability.name;
                    return (
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
                      {seat}{seat !== "不限" ? <small>{capability.regular ? "可自动提交" : "查询／人工"}{capability.alternate ? " · 可自动候补" : ""}</small> : null}
                    </button>
                  );})}
                </div>
                {!seatCapabilities.length ? <small className="field-help">席别能力尚未加载，请检查运行时状态。</small> : null}
                {selectedSeats.length > 1 ? <span className="trip-train-order" aria-label="席别优先顺序">
                  {selectedSeats.map((seat, index) => <span key={seat}>{index + 1}. {seat}
                    <button type="button" aria-label={`上移席别 ${seat}`} disabled={index === 0} onClick={() => {
                      const next = [...selectedSeats]; [next[index - 1], next[index]] = [next[index], next[index - 1]];
                      update({ seat_keyword: next.join("，") });
                    }}>↑</button>
                    <button type="button" aria-label={`下移席别 ${seat}`} disabled={index === selectedSeats.length - 1} onClick={() => {
                      const next = [...selectedSeats]; [next[index + 1], next[index]] = [next[index], next[index + 1]];
                      update({ seat_keyword: next.join("，") });
                    }}>↓</button>
                  </span>)}
                </span> : null}
              </div>
            </div>

            <div className="trip-form-row trip-form-row--split">
              <div className="trip-field">
                <span>乘客</span>
                <div className="passenger-strip">
                  {passengerNames.map((name, index) => (
                    <span className="passenger-tag" key={`${name}-${index}`}>
                      {name}
                      <button
                        aria-label={`移除乘客 ${name}`}
                        onClick={() => removePassenger(index)}
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
                {passengerError ? <small className="trip-date-hint" role="alert">{passengerError}</small> : null}
                <small className="field-help">姓名不代表票种。普通订单按完整姓名勾选后，须回读确认为成人票才会提交；候补须在乘客列表明确标为成人。学生、儿童请在官方页面处理。</small>
                <button type="button" className="trip-station-refresh" disabled={readingPassengers || !!busy || monitoring}
                  aria-busy={readingPassengers} onClick={() => void readPassengers()}>
                  {readingPassengers ? "正在读取官方乘客…" : "从官方页面读取乘客"}
                </button>
                <small className="field-help">{monitoring ? "监控运行中，请停止监控后读取乘客。" : "自动打开官方乘车人列表，读取后返回原页面。"}</small>
                {passengerCandidates?.warning ? <small className="field-help" role="status">{passengerCandidates.warning}</small> : null}
                {passengerCandidates?.items.length ? <div className="trip-route-choices" aria-label="官方页面乘客候选">
                  {passengerCandidates.items.map((candidate, index) => <button type="button" key={`${candidate.name}-${candidate.identity_hint}-${index}`}
                    disabled={candidate.ambiguous || candidate.ticket_type !== "adult" || passengerNames.includes(candidate.name)}
                    onClick={() => addCandidate(candidate)}>{candidate.name} · {candidate.identity_hint || "证件摘要未提供"} · {
                      candidate.ambiguous ? "同名需人工核对" : candidate.ticket_type === "adult" ? "成人" : candidate.ticket_type === "unknown" ? "列表未标票种，可手动填写姓名后核对" : "票种不支持自动交易"
                    }</button>)}
                </div> : null}
              </div>
            </div>
          </PreferenceSection>
          <div className="trip-strategy-sections">
            <PreferenceSection
              id="trip-query"
              title="查询策略"
              description="调整查询频率、优先级与座位偏好"
              defaultOpen={window.matchMedia("(min-width: 1400px)").matches}
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
              <p className="field-help">保持会话会定期检查登录，临近起售暂停检查；登录失效仍需重新登录。智能轮询在超时或限频时放慢查询，不延迟首次查询。</p>
            </PreferenceSection>
            <TimerSettings config={config} update={update} windowDays={windowDays} />
            <PreferenceSection
              id="trip-automation"
              title="自动化"
              description={
                config.auto_submit || config.auto_alternate
                  ? "已启用 · 核验与支付需人工完成"
                  : "自动提交与自动候补默认关闭"
              }
            >
              <label className="trip-field">
                <span>候补组合</span>
                <Select aria-label="候补组合" className="trip-select" value={config.alternate_mode ?? "single"}
                  options={[{ value: "single", label: "首个可用组合" }, { value: "multiple", label: "多个已配置组合" }]}
                  onChange={value => update({ alternate_mode: value })} />
              </label>
              {config.alternate_mode === "multiple" ? <label className="trip-field">
                <span>候补组合上限</span>
                <InputNumber aria-label="候补组合上限" min={1} max={ORDER_POLICY.max_combinations} precision={0}
                  value={config.alternate_max_combinations ?? ORDER_POLICY.alternate_max_combinations}
                  onChange={value => { if (value !== null) update({ alternate_max_combinations: value }); }} />
                <small className="field-help">最多{ORDER_POLICY.max_dates}个日期。按配置的日期、车次和席别选择页面可用组合；统一核对并提交一个候补订单，实际清单可在订单中心查看。</small>
              </label> : null}
              <label className="switch-row">
                <Switch aria-label="持续订单核对" checked={config.order_watch_enabled ?? ORDER_POLICY.order_watch_enabled}
                  onChange={value => update({ order_watch_enabled: value })} />
                <span>持续订单核对</span>
              </label>
              {(config.order_watch_enabled ?? ORDER_POLICY.order_watch_enabled) ? <label className="trip-field">
                <span>订单核对间隔（秒）</span>
                <InputNumber aria-label="订单核对间隔（秒）" precision={0}
                  min={ORDER_POLICY.min_watch_interval_seconds} max={ORDER_POLICY.max_watch_interval_seconds}
                  value={config.order_watch_interval_seconds ?? ORDER_POLICY.order_watch_interval_seconds}
                  onChange={value => { if (value !== null) update({ order_watch_interval_seconds: value }); }} />
                <small className="field-help">取得订单号后在独立标签页核对，保留付款页面。候补生效后持续等待兑现；异常时放慢，可在订单中心停止。退出或重启后需点击继续核对。</small>
              </label> : null}
              <label className="trip-field">
                <span>候补截止</span>
                <AutoComplete
                  aria-label="候补截止"
                  className="trip-select"
                  placeholder="选择截止时间，或输入完整日期时间"
                  options={["开车前20分钟", "开车前1小时", "开车前2小时", "开车前3小时", "开车前6小时", "开车前12小时", "开车前1天"].map(value => ({ value }))}
                  suffixIcon={<ChevronDown size={14} style={{ pointerEvents: "none" }} />}
                  value={config.alternate_deadline === "开车前60分钟" ? "开车前1小时" : config.alternate_deadline}
                  onChange={(value) =>
                    update({ alternate_deadline: value })
                  }
                />
              </label>
              <p>
                可选择常用截止时间，也可输入完整日期时间（如 2026-10-01 18:00）；提交时以官方页面实际提供的选项为准。
              </p>{" "}
              <div className="trip-advanced-risk">
                <RiskToggle
                  checked={config.auto_submit}
                  title={config.auto_submit ? "自动提交已启用" : "自动提交关闭"}
                  description="开启后按设置的目标自动提交订单并确认，无需人工点击确认；核验与支付需人工完成。"
                  onChange={(checked) =>
                    void guardedAutomation("auto_submit", checked)
                  }
                />
                <RiskToggle
                  checked={config.auto_alternate}
                  title={
                    config.auto_alternate ? "候补排队已启用" : "候补排队关闭"
                  }
                  description="按配置提交已核对的候补组合；人工支付预付款后才生效。实验性功能，需核对官方订单。"
                  onChange={(checked) =>
                    void guardedAutomation("auto_alternate", checked)
                  }
                />
              </div>
            </PreferenceSection>
          </div>
        </div>
        <footer className="trip-setup-footer">
          <Button
            icon={<Save size={15} />}
            loading={busy === "saveConfig"}
            disabled={!tripInitialized}
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
          <Button loading={busy === "analyzeQuery"}
            onClick={() => void runCommand("analyzeQuery", { config: { ...config, train_code: "" } })}>
            查询本路线全部车次
          </Button>
        </footer>
      </section>
    </div>
  );
}
