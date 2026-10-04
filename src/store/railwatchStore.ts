import type { RehearsalCheck, RehearsalReport, RehearsalStarted } from "../lib/rehearsal";
import { createStore } from "zustand/vanilla";
import { DEFAULT_QUERY_STRATEGY } from "../lib/queryStrategy";
import { DEFAULT_DATE_STRATEGY } from "../lib/dateStrategy";
import { DEFAULT_ORDER_POLICY } from "../lib/orderPolicy";
import { conditionsMatch, mergeQuerySnapshots, queryFamily, queryRows, type QueryViews } from "../lib/queryResults";
import type {
  HumanActionPayload,
  LogEntry,
  MonitorTickPayload,
  NotifyPayload,
  QueryResultRow,
  QueryAttempt,
  RailWatchConfig,
  RailWatchPage,
  RailWatchStatus,
  ResultsPayload,
  RuntimeInfo,
  TicketHit,
  TripDraftReadResult,
} from "../types";

export function tripFingerprint(config: RailWatchConfig) {
  return JSON.stringify(Object.fromEntries(Object.entries(config).filter(([key]) => key !== "query_jobs").sort(([a], [b]) => a.localeCompare(b))));
}

function humanActionKey(action: HumanActionPayload) {
  return action.event_id || JSON.stringify([action.run_id, action.title, action.message]);
}

export const defaultStatus: RailWatchStatus = {
  phase: "idle",
  environment_ready: false,
  login_ready: false,
  query_ready: false,
  monitoring: false,
  auto_submit_enabled: false,
  auto_alternate_enabled: false,
  risk_level: "notice",
  status_message: "就绪",
  error_message: "",
  current_config: {},
  hits: [],
  summary: "就绪",
};

export const defaultRuntimeInfo: RuntimeInfo = {
  app_display_name: "RailWatch 12306",
  app_version: "未知",
  app_slug: "railwatch-12306",
  pages: ["仪表盘", "行程设置", "购票监控", "订单中心", "系统设置"],
  data_dir: "",
  data_dir_writable: false,
  data_dir_free_bytes: 0,
  chromedriver_path: "",
  chrome_version: "未知",
  core_available: false,
  core_import_error: "",
  selenium_available: false,
  chromedriver_manager_available: false,
  network_ok: false,
  network_label: "检测中",
  railway_ok: false,
  railway_label: "检测中",
  proxy_configured: false,
  proxy_label: "检测中",
  proxy_value: "",
  state: defaultStatus,
};

export const defaultConfig: RailWatchConfig = {
  ...DEFAULT_ORDER_POLICY,
  from_station_cn: "北京",
  to_station_cn: "上海",
  date: "",
  train_code: "",
  seat_keyword: "",
  interval: 5,
  query_timeout: 40,
  auto_submit: false,
  seat_prefer: "无偏好",
  passenger_count: 1,
  prepare_time: 2,
  keep_alive: true,
  passengers: "",
  auto_alternate: false,
  alternate_deadline: "开车前60分钟",
  date_range: "±1天",
  smart_rate: true,
  timer_enabled: false,
  target_time: "00:00:00",
  sale_at: "",
  sale_time_source: "manual",
  sale_time_checked_at: "",
  burst_window_seconds: 45,
  prewarm_lead_seconds: 120,
  config_version: 2,
  automation_route: "compliance_alerts",
  ...DEFAULT_QUERY_STRATEGY,
  ...DEFAULT_DATE_STRATEGY,
};

export type RailWatchStore = {
  rehearsalEnabled: boolean;
  setRehearsalEnabled: (enabled: boolean) => void;
  rehearsal: { activeId: string | null; trigger: "manual" | "task" | null; checks: RehearsalCheck[]; report: RehearsalReport | null; fingerprint: string | null; pendingFingerprint: string | null; lastStartedAt?: number; historyCleared?: boolean };
  prepareRehearsal: (config: RailWatchConfig) => void;
  applyRehearsalStarted: (payload: RehearsalStarted) => void;
  applyRehearsalStep: (payload: { rehearsal_id: string; check: RehearsalCheck }) => void;
  applyRehearsalFinished: (payload: { report: RehearsalReport }) => void;
  resetRehearsalProgress: () => void;
  clearRehearsalHistory: () => void;
  loadRehearsalHistory: (report: RehearsalReport) => void;
  runtime: RuntimeInfo;
  status: RailWatchStatus;
  config: RailWatchConfig;
  savedConfig: RailWatchConfig | null;
  savedAt: number | null;
  configSaveError: string | null;
  draftRead: TripDraftReadResult;
  tripInitialized: boolean;
  editRevision: number;
  draftRevision: number;
  draftSaveState: "idle" | "editing" | "saving" | "saved" | "error";
  draftSavedAt: number | null;
  draftError: string | null;
  initializeTrip: (config: RailWatchConfig, savedAt: number | null, draft: TripDraftReadResult) => void;
  applyDraft: () => void;
  dismissDraft: () => void;
  markConfigSaved: (config: RailWatchConfig, at: number) => void;
  markConfigSaveError: (reason: string) => void;
  markDraftSaving: (editRevision: number) => void;
  markDraftSaved: (editRevision: number, revision: number, at: number) => void;
  markDraftError: (editRevision: number, reason: string) => void;
  logs: LogEntry[];
  pausedLogs: LogEntry[];
  droppedLogs: number;
  retiredRuns: string[];
  results: QueryResultRow[];
  queryViews: QueryViews;
  activeQuery: QueryAttempt | null;
  applyQueryStarted: (attempt: QueryAttempt) => void;
  queryConfig: RailWatchConfig | null;
  manualQueryId: string | null;
  manualQueryPending: boolean;
  manualQueryError: string | null;
  beginManualQuery: (id: string, config: RailWatchConfig) => void;
  endManualQuery: (id: string, error?: string) => void;
  monitorLoops: number;
  hits: TicketHit[];
  notifications: NotifyPayload[];
  lastHumanAction: HumanActionPayload | null;
  dismissedHumanActionKey: string | null;
  activePage: RailWatchPage;
  logPaused: boolean;
  eventPanelVisible: boolean;
  applyRuntimeInfo: (runtime: RuntimeInfo) => void;
  applyRuntimeMetadata: (runtime: RuntimeInfo) => void;
  applyRuntimeLabels: (patch: Partial<Pick<RuntimeInfo, "chromedriver_path" | "chrome_version">>) => void;
  applyState: (status: RailWatchStatus) => void;
  applyLog: (entry: LogEntry) => void;
  applyResults: (payload: ResultsPayload) => void;
  applyMonitorTick: (payload: MonitorTickPayload) => void;
  applyNotify: (payload: NotifyPayload) => void;
  applyHumanAction: (payload: HumanActionPayload) => void;
  clearHumanAction: () => void;
  setConfig: (patch: Partial<RailWatchConfig>) => void;
  pageSection: string | null;
  setActivePage: (page: RailWatchPage, section?: string) => void;
  setLogPaused: (paused: boolean) => void;
  setEventPanelVisible: (visible: boolean) => void;
  clearLogs: () => void;
  errorCount: () => number;
  filteredLogs: (filter: string) => LogEntry[];
};

const logLevelByFilter: Record<string, string | string[]> = {
  信息: ["INFO", "SUCCESS"],
  警告: "WARN",
  错误: "ERROR",
  成功: "SUCCESS",
};

export const MAX_LOG_ENTRIES = 1000;

export function createRailWatchStore() {
  let nextLogId = 0;
  return createStore<RailWatchStore>((set, get) => ({
    rehearsalEnabled: false,
    setRehearsalEnabled: rehearsalEnabled => set({ rehearsalEnabled }),
    rehearsal: { activeId: null, trigger: null, checks: [], report: null, fingerprint: null, pendingFingerprint: null },
    prepareRehearsal: config => set(state => ({ rehearsal: { ...state.rehearsal, pendingFingerprint: tripFingerprint(config) } })),
    applyRehearsalStarted: payload => set(state => ({ rehearsal: { ...state.rehearsal,
      activeId: payload.rehearsal_id, trigger: payload.trigger, checks: payload.checks,
      pendingFingerprint: payload.trigger === "task" ? tripFingerprint({ ...state.config, ...state.status.current_config }) : state.rehearsal.pendingFingerprint } })),
    applyRehearsalStep: payload => set(state => state.rehearsal.activeId !== payload.rehearsal_id ? {} : ({ rehearsal: {
      ...state.rehearsal, checks: state.rehearsal.checks.map(c => c.id === payload.check.id ? payload.check : c) } })),
    applyRehearsalFinished: ({ report }) => set(state => state.rehearsal.activeId !== report.rehearsal_id ? {} : ({ rehearsal: {
      ...state.rehearsal, activeId: null, checks: report.checks, report, fingerprint: state.rehearsal.pendingFingerprint, pendingFingerprint: null } })),
    resetRehearsalProgress: () => set(state => ({ rehearsal: { ...state.rehearsal, activeId: null, pendingFingerprint: null } })),
    clearRehearsalHistory: () => set(state => ({ rehearsal: { ...state.rehearsal, report: null, checks: [], fingerprint: null,
      pendingFingerprint: null, lastStartedAt: state.rehearsal.report?.started_at ?? state.rehearsal.lastStartedAt, historyCleared: true } })),
    loadRehearsalHistory: report => set(state => state.rehearsal.activeId || state.rehearsal.report || state.rehearsal.historyCleared ? {} : ({ rehearsal: { ...state.rehearsal, report, fingerprint: null } })),
    runtime: defaultRuntimeInfo,
    status: defaultStatus,
    config: defaultConfig,
    savedConfig: null,
    savedAt: null,
    configSaveError: null,
    draftRead: { status: "missing", draft: null, warning: null },
    tripInitialized: false,
    editRevision: 0,
    draftRevision: 0,
    draftSaveState: "idle",
    draftSavedAt: null,
    draftError: null,
    initializeTrip: (config, savedAt, draft) => set({ config: { ...defaultConfig, ...config },
      savedConfig: { ...defaultConfig, ...config }, savedAt, configSaveError: null, draftRead: draft, tripInitialized: true,
      editRevision: 0, draftRevision: draft.status === "available" ? draft.draft.revision : 0,
      draftSaveState: "idle", draftSavedAt: draft.status === "available" ? draft.draft.saved_at : null,
      draftError: draft.status === "invalid" ? draft.warning : null }),
    applyDraft: () => {
      const draft = get().draftRead;
      if (draft.status !== "available") return;
      get().setConfig({ ...draft.draft.config });
      set({ draftRead: { status: "missing", draft: null, warning: null } });
    },
    dismissDraft: () => set({ draftRead: { status: "missing", draft: null, warning: null } }),
    markConfigSaved: (config, at) => set({ savedConfig: { ...config }, savedAt: at, configSaveError: null }),
    markConfigSaveError: (reason) => set({ configSaveError: reason }),
    markDraftSaving: (revision) => {
      if (revision === get().editRevision) set({ draftSaveState: "saving", draftError: null });
    },
    markDraftSaved: (editRevision, revision, at) => set({ draftRevision: Math.max(get().draftRevision, revision),
      draftSavedAt: at, ...(editRevision === get().editRevision ? { draftSaveState: "saved" as const, draftError: null } : {}) }),
    markDraftError: (revision, reason) => {
      if (revision === get().editRevision) set({ draftSaveState: "error", draftError: reason });
    },
    logs: [],
    pausedLogs: [],
    droppedLogs: 0,
    retiredRuns: [],
    results: [],
    queryViews: {},
    activeQuery: null,
    queryConfig: null,
    manualQueryId: null,
    manualQueryPending: false,
    manualQueryError: null,
    monitorLoops: 0,
    hits: [],
    notifications: [],
    lastHumanAction: null,
    dismissedHumanActionKey: null,
    activePage: "仪表盘",
    pageSection: null,
    logPaused: false,
    eventPanelVisible: false,
    applyRuntimeInfo: (runtime) => {
      const current = get().status;
      if (current.task?.run_id && !runtime.state.task?.run_id) {
        set({ runtime: { ...runtime, state: current } });
        return;
      }
      set({ runtime });
      get().applyState(runtime.state);
    },
    applyRuntimeMetadata: (runtime) => {
      // Periodic health requests can complete after a newer state event. Keep
      // that event as the authority and refresh only runtime metadata here.
      set({ runtime: { ...runtime, state: get().status } });
    },
    applyRuntimeLabels: (patch) => {
      set({ runtime: { ...get().runtime, ...patch } });
    },
    applyState: (status) => {
      const incoming = status.task?.run_id;
      const current = get().status.task?.run_id;
      if (incoming && get().retiredRuns.includes(incoming)) return;
      if (incoming && incoming === current && (status.task?.sequence ?? 0) < (get().status.task?.sequence ?? 0)) return;
      const changed = Boolean(incoming && incoming !== current);
      const orderResolved = Boolean(status.order?.order_id && !status.order.recovery_required &&
        ["pending_payment", "active", "fulfilled"].includes(status.order.status));
      set({ status, hits: status.hits,
        ...(!status.monitoring && !get().manualQueryPending ? { activeQuery: null } : {}),
        ...(orderResolved ? { lastHumanAction: null } : {}),
        ...(changed ? { monitorLoops: 0, results: [], queryViews: {}, activeQuery: null, queryConfig: { ...get().config, ...status.current_config },
          manualQueryId: null, manualQueryPending: false, manualQueryError: null, lastHumanAction: null,
          retiredRuns: current ? [...get().retiredRuns, current].slice(-1000) : get().retiredRuns } : {}),
        ...(changed ? { dismissedHumanActionKey: null } : {}),
        ...(status.human_action && (changed || humanActionKey(status.human_action) !== get().dismissedHumanActionKey)
          ? { lastHumanAction: status.human_action } : {}),
      });
    },
    applyLog: (entry) => {
      if (entry.run_id && entry.run_id !== get().status.task?.run_id) return;
      const key = get().logPaused ? "pausedLogs" : "logs";
      const entries = [...get()[key], { ...entry, id: ++nextLogId }];
      set({ [key]: entries.slice(-MAX_LOG_ENTRIES), droppedLogs: get().droppedLogs + Math.max(0, entries.length - MAX_LOG_ENTRIES) });
    },
    applyResults: (payload) => {
      if (payload.run_id && payload.run_id !== get().status.task?.run_id) return;
      if (payload.snapshots) {
        if (payload.request_id !== get().manualQueryId || !get().manualQueryPending || !get().queryConfig || get().status.monitoring) return;
        const merged = mergeQuerySnapshots(get().queryViews, payload.snapshots.filter(s => s.run_id === null),
          `manual:${payload.request_id}`, get().queryConfig!);
        if (merged.accepted) set({ queryViews: merged.views, results: queryRows(merged.views), activePage: "购票监控",
          ...(payload.snapshots.some(s => s.query_id === get().activeQuery?.query_id) ? { activeQuery: null } : {}) });
        return;
      }
      if (get().manualQueryId || Object.keys(get().queryViews).length) return;
      set({ results: payload.rows, activePage: "购票监控" });
    },
    applyMonitorTick: (payload) => {
      if (payload.run_id && payload.run_id !== get().status.task?.run_id) return;
      if (payload.snapshot) {
        if (!payload.run_id || payload.snapshot.run_id !== payload.run_id || get().manualQueryId || !get().status.monitoring) return;
        const config = get().queryConfig ?? { ...get().config, ...get().status.current_config };
        const merged = mergeQuerySnapshots(get().queryViews, [payload.snapshot], `run:${payload.run_id}`, config);
        if (merged.accepted) set({ queryConfig: config, queryViews: merged.views, results: queryRows(merged.views), monitorLoops: Math.max(get().monitorLoops, payload.loop),
          ...(payload.snapshot.query_id === get().activeQuery?.query_id ? { activeQuery: null } : {}) });
        return;
      }
      if (get().manualQueryId || Object.keys(get().queryViews).length) return;
      set({ results: payload.rows, monitorLoops: payload.loop });
    },
    beginManualQuery: (id, config) => {
      if (get().status.monitoring) return;
      const same = get().queryConfig && queryFamily(get().queryConfig!) === queryFamily(config);
      set({ manualQueryId: id, manualQueryPending: true, manualQueryError: null, activeQuery: null, queryConfig: { ...config },
        ...(same ? {} : { queryViews: {}, results: [] }) });
    },
    endManualQuery: (id, error) => {
      if (get().manualQueryId !== id) return;
      set({ manualQueryPending: false, manualQueryError: error ?? null, activeQuery: null });
    },
    applyQueryStarted: (attempt) => {
      if (attempt.run_id ? attempt.run_id !== get().status.task?.run_id || !get().status.monitoring
        : attempt.request_id !== get().manualQueryId || !get().manualQueryPending) return;
      const config = get().queryConfig;
      if (!config || !conditionsMatch(attempt.conditions, config) || !Number.isSafeInteger(attempt.sequence) || attempt.sequence < 0) return;
      if (get().activeQuery && attempt.sequence <= get().activeQuery!.sequence) return;
      const owner = attempt.run_id ? `run:${attempt.run_id}` : `manual:${attempt.request_id}`;
      if (Object.values(get().queryViews).some(v => v.owner === owner && v.latest.sequence >= attempt.sequence)) return;
      set({ activeQuery: attempt });
    },
    applyNotify: (payload) => {
      if (payload.run_id && payload.run_id !== get().status.task?.run_id) return;
      const nextHits = payload.hit ? [...get().hits, payload.hit] : get().hits;
      set({
        notifications: [...get().notifications, payload],
        hits: nextHits,
      });
    },
    applyHumanAction: (payload) => {
      if (payload.run_id && payload.run_id !== get().status.task?.run_id) return;
      if (humanActionKey(payload) === get().dismissedHumanActionKey) return;
      set({ lastHumanAction: payload });
    },
    clearHumanAction: () => {
      set({ dismissedHumanActionKey: get().lastHumanAction ? humanActionKey(get().lastHumanAction!) : null, lastHumanAction: null });
    },
    setConfig: (patch) => {
      const config = { ...get().config, ...patch };
      if (tripFingerprint(config) === tripFingerprint(get().config)) return;
      const changed = queryFamily(config) !== queryFamily(get().config);
      set({ config, editRevision: get().editRevision + 1, draftSaveState: "editing", draftError: null,
        ...(!get().status.monitoring && changed ? { queryViews: {}, results: [], queryConfig: null, activeQuery: null,
        manualQueryId: null, manualQueryPending: false,
        manualQueryError: get().manualQueryPending ? "查询条件已改变，本次查询结果已作废" : null } : {}) });
    },
    setActivePage: (page, section) => {
      set({ activePage: page, pageSection: section ?? null });
    },
    setLogPaused: (paused) => {
      if (!paused && get().pausedLogs.length > 0) {
        const combined = [...get().logs, ...get().pausedLogs];
        set({ logs: combined.slice(-MAX_LOG_ENTRIES), droppedLogs: get().droppedLogs + Math.max(0, combined.length - MAX_LOG_ENTRIES), pausedLogs: [], logPaused: false });
        return;
      }
      set({ logPaused: paused });
    },
    setEventPanelVisible: (visible) => {
      set({ eventPanelVisible: visible });
    },
    clearLogs: () => {
      set({ logs: [], pausedLogs: [], droppedLogs: 0 });
    },
    errorCount: () => get().logs.filter((entry) => entry.level === "ERROR").length,
    filteredLogs: (filter) => {
      const level = logLevelByFilter[filter];
      if (!level) {
        return get().logs;
      }
      const levels = Array.isArray(level) ? level : [level];
      return get().logs.filter((entry) => levels.includes(entry.level));
    },
  }));
}

export const railwatchStore = createRailWatchStore();
