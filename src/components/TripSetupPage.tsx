import { useEffect, useMemo, useState } from "react";
import { Alert, Button, ConfigProvider, Input, InputNumber, Select, Switch } from "antd";
import { AutomationSection } from "./AutomationSettings";
import { DATE_STRATEGIES, DATE_SCAN_BUDGET, dateStrategy, dateStrategySummary } from "../lib/dateStrategy";
import { automationConfigIssue } from "../lib/automationReadiness";
import {
  ArrowLeftRight,
  BarChart3,
  Building2,
  CalendarDays,
  FolderOpen,
  Plus,
  RefreshCw,
  Save,
  Star,
  TrainFront,
  UserRoundSearch,
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
import { Hint } from "./DisplayPrimitives";
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
    {/* The suggestion list floats over the form so typing never shifts the neighbouring field. */}
    <div className="station-combobox">
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
    </div>
    {warning ? <small className="trip-date-hint" role="status">{warning}</small> : null}
    {!focused && searched && !warning && value.trim() && !items.some(item => item.name === value.trim())
      ? <small className="trip-date-hint" role="status">请从联想中选择完整站名</small> : null}
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
      setTrainNotice("路线已变化，现有目标车次会保留，请核对。");
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
          <div className="trip-save-status" role="status">
            <i className={"lamp " + (formalDirty ? "wait" : "go")} aria-hidden="true" />
            <strong>{formalDirty ? "有未保存的修改" : "已保存"}</strong>
            {savedAt !== null ? <span className="mono">{formatSavedAt(savedAt)}</span> : null}
            {formalDirty && draftSaveState === "saving" ? <span>草稿保存中…</span> : null}
            {formalDirty && draftSaveState === "saved" ? <span>草稿已自动保存</span> : null}
            {monitoring ? <span>修改将在下次运行生效</span> : null}
            {!tripInitialized ? <span role="alert">已保存的行程尚未加载，加载完成前暂不可编辑。</span> : null}
            {configSaveError ? <span role="alert">保存失败：{configSaveError}</span> : null}
            {draftError ? <span role="alert">草稿保存失败：{draftError}</span> : null}
          </div>
          <Button
            className="trip-load-button"
            icon={<FolderOpen size={15} />}
            loading={busy === "loadConfig"}
            disabled={!tripInitialized}
            onClick={() => void loadConfig()}
          >
            恢复上次保存
          </Button>
        </header>
        {draftRead.status === "available" ? <div className="trip-draft-recovery" role="group" aria-label="恢复行程草稿">
          <span>发现未保存的草稿 · <span className="mono">{formatSavedAt(draftRead.draft.saved_at)}</span></span>
          <Button size="small" type="primary" onClick={applyDraft}>恢复草稿</Button>
          <Button size="small" type="text" onClick={dismissDraft}>使用已保存配置</Button>
        </div> : null}
        {draftRead.status === "invalid" ? <div className="trip-draft-recovery" role="alert">{draftRead.warning}</div> : null}

        {/* Edits made before the saved trip loads would be based on defaults
            (e.g. adding a passenger would drop the saved ones), so wait for it. */}
        <ConfigProvider componentDisabled={!tripInitialized}>
        <fieldset className="trip-setup-form-scroll" disabled={!tripInitialized}>
          <PreferenceSection
            id="trip-basics"
            title="路线与乘客"
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
            <div className="trip-route-bar">
              {choices.recent_routes.length ? <div className="trip-route-choices" aria-label="最近路线">
                <span>最近</span>{choices.recent_routes.map(route => <button type="button"
                  key={`${route.from_station}-${route.to_station}`} onClick={() => setRoute(route.from_station, route.to_station)}>
                  {route.from_station} → {route.to_station}
                </button>)}
              </div> : null}
              <Button size="small" className="trip-station-refresh" icon={<RefreshCw size={13} />}
                loading={busy === "refreshStations"} onClick={() => void runCommand("refreshStations", {}, "站码数据已更新").then(result => {
                  if (result) setStationRevision(value => value + 1);
                })}>更新站码数据</Button>
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
                {rangeStatus.invalid ? <small className="trip-date-hint">请输入有效日期</small>
                  : config.date_range !== "单日" || rangeStatus.skipped.length ? <small className="trip-date-hint">
                    实际查询 {rangeStatus.valid.map(date => date.slice(5)).join("、") || "无"}
                    {rangeStatus.skipped.length ? ` · 跳过 ${rangeStatus.skipped.map(date => date.slice(5)).join("、")}` : ""}
                  </small> : null}
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
                <span className="trip-field-label-with-help">车次
                  <Hint text="可填写多个车次，按顺序优先。留空则查询本路线全部车次，可在查询结果中勾选加入。" /></span>
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
                  <Button className="trip-inline-button" icon={<Star size={14} />} onClick={() => void saveFavorites()} type="default">
                    收藏
                  </Button>
                </span>
                {currentFavorite?.trains.length ? <span className="trip-route-choices">
                  <span>收藏</span><button type="button" onClick={() => update({ train_code: currentFavorite.trains.join(", ") })}>
                    应用 {currentFavorite.trains.join("、")}
                  </button>
                </span> : null}
                {selectedTrains.length > 1 ? <span className="trip-train-order" aria-label="车次优先顺序">
                  {selectedTrains.map((code, index) => <span key={code}>
                    <em>{index + 1}</em>{code}
                    <button type="button" aria-label={`上移 ${code}`} disabled={index === 0} onClick={() => moveTrain(index, -1)}>↑</button>
                    <button type="button" aria-label={`下移 ${code}`} disabled={index === selectedTrains.length - 1} onClick={() => moveTrain(index, 1)}>↓</button>
                  </span>)}
                </span> : null}
              </div>
              <div className="trip-field">
                <span className="trip-field-label-with-help">多日期策略
                  <Hint label="多日期策略" text={dateStrategySummary(config)} /></span>
                <Select aria-label="多日期策略" className="trip-select" value={dateStrategy(config)}
                  disabled={dateRange === "单日"}
                  options={Object.entries(DATE_STRATEGIES).map(([value, policy]) => ({ value, label: policy.label }))}
                  onChange={value => update({ date_strategy: value })} />
                {dateStrategy(config) === "inventory_first" && dateRange !== "单日" ? <label className="trip-field">
                  <span>跨日期扫描预算（秒）</span>
                  <InputNumber aria-label="跨日期扫描预算（秒）" className="trip-select"
                    min={DATE_SCAN_BUDGET.min_budget_seconds} max={DATE_SCAN_BUDGET.max_budget_seconds} precision={0}
                    value={config.date_scan_budget_seconds ?? DATE_SCAN_BUDGET.scan_budget_seconds}
                    onChange={value => { if (value !== null) update({ date_scan_budget_seconds: value }); }} />
                </label> : null}
              </div>
            </div>

            <div className="trip-form-row">
              <div className="trip-field">
                <span className="trip-field-label-with-help">席别
                  <Hint text="可多选，按选择顺序优先。标记「仅提醒」的席别只查询和通知，由你在官网购买；卧铺铺位由官网分配。" /></span>
                <div aria-label="席别" className="chip-group" role="group">
                  {[{ name: "不限", query: true, regular: true, alternate: true }, ...seatCapabilities.filter(seat => seat.query)].map((capability) => {
                    const seat = capability.name;
                    const limit = !capability.regular && !capability.alternate ? "仅提醒"
                      : !capability.alternate ? "不可候补" : !capability.regular ? "仅候补" : "";
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
                      {seat}{limit ? <small>{limit}</small> : null}
                    </button>
                  );})}
                </div>
                {!seatCapabilities.length ? <small className="field-help">席别信息尚未加载，请检查运行环境。</small> : null}
                {selectedSeats.length > 1 ? <span className="trip-train-order" aria-label="席别优先顺序">
                  {selectedSeats.map((seat, index) => <span key={seat}><em>{index + 1}</em>{seat}
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
                <span className="trip-field-label-with-help">乘客
                  <Hint text="自动交易仅支持成人票：普通订单勾选后回读确认票种，候补须在官方乘客列表中标为成人。学生、儿童票请在官网办理。" /></span>
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
                    <Input
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
                    <Button type="text" aria-label="添加乘客" icon={<Plus size={14} />} onClick={addPassenger}>
                      添加乘客
                    </Button>
                    <Button className="trip-station-refresh" icon={<UserRoundSearch size={14} />}
                      disabled={readingPassengers || !!busy || monitoring}
                      aria-busy={readingPassengers} onClick={() => void readPassengers()}>
                      {readingPassengers ? "正在读取官方乘客…" : "从官方页面读取乘客"}
                    </Button>
                  </span>
                </div>
                {passengerError ? <small className="trip-date-hint" role="alert">{passengerError}</small> : null}
                {monitoring ? <small className="field-help">监控运行中，请停止监控后读取乘客。</small> : null}
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
              description={`${PRIORITIES[priority].label} · 每 ${config.interval} 秒`}
              defaultOpen={window.matchMedia("(min-width: 1400px)").matches}
            >
              <div className="trip-form-row trip-form-row--split">
                <div className="trip-field">
                  <span className="trip-field-label-with-help">
                    优先级
                    <Hint text="速度优先缩短查询等待，适合起售时刻；成功率优先查询更稳、等待更长，适合长时间监控。选择后会套用推荐参数。" />
                  </span>
                  <SegmentedControl
                    ariaLabel="优先级"
                    options={["速度优先", "成功率优先"] as const}
                    value={PRIORITIES[priority].label}
                    onChange={handlePriorityChange}
                  />
                  {customized ? <small className="field-help">已自定义 · 重新选择优先级可恢复推荐参数</small> : null}
                </div>
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
              </div>
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
                    <Hint label="随机延迟" text={preview.detail} />
                  </span>
                  <div className="trip-readonly-pill">
                    {preview.label} 秒
                  </div>
                </div>
                <div className="trip-field">
                  <span className="trip-field-label-with-help">
                    请求模式
                    <Hint text="查询间隔与超时的预设。快速、均衡、保守依次放缓节奏，查询更稳。" />
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
                <span className="switch-row">
                  <Switch
                    aria-label="保持会话"
                    checked={config.keep_alive}
                    onChange={(checked) => update({ keep_alive: checked })}
                  />
                  <span>保持会话</span>
                  <Hint text="定期检查登录状态，临近起售时暂停检查。登录失效后仍需重新登录。" />
                </span>
                <span className="switch-row">
                  <Switch
                    aria-label="智能轮询"
                    checked={config.smart_rate}
                    onChange={(checked) => update({ smart_rate: checked })}
                  />
                  <span>智能轮询</span>
                  <Hint text="遇到超时或限频时自动放慢查询，不影响首次查询。" />
                </span>
              </div>
            </PreferenceSection>
            <AutomationSection config={config} update={update} runCommand={runCommand} confirm={confirm}
              busy={busy} />
            <TimerSettings config={config} update={update} windowDays={windowDays} />
          </div>
        </fieldset>
        </ConfigProvider>
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
            查询全部车次
          </Button>
        </footer>
      </section>
    </div>
  );
}
