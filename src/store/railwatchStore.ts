import { createStore } from "zustand/vanilla";
import type {
  LogEntry,
  MonitorTickPayload,
  NotifyPayload,
  QueryResultRow,
  RailWatchConfig,
  RailWatchPage,
  RailWatchStatus,
  ResultsPayload,
  RuntimeInfo,
  TicketHit,
} from "../types";

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
  pages: ["仪表盘", "行程设置", "购票监控", "系统设置"],
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
  alternate_deadline: "18:00",
  date_range: "±1天",
  smart_rate: true,
  timer_enabled: false,
  target_time: "00:00:00",
};

export type RailWatchStore = {
  runtime: RuntimeInfo;
  status: RailWatchStatus;
  config: RailWatchConfig;
  logs: LogEntry[];
  pausedLogs: LogEntry[];
  results: QueryResultRow[];
  monitorLoops: number;
  hits: TicketHit[];
  notifications: NotifyPayload[];
  activePage: RailWatchPage;
  logPaused: boolean;
  eventPanelVisible: boolean;
  applyRuntimeInfo: (runtime: RuntimeInfo) => void;
  applyRuntimeLabels: (patch: Partial<Pick<RuntimeInfo, "chromedriver_path" | "chrome_version">>) => void;
  applyState: (status: RailWatchStatus) => void;
  applyLog: (entry: LogEntry) => void;
  applyResults: (payload: ResultsPayload) => void;
  applyMonitorTick: (payload: MonitorTickPayload) => void;
  applyNotify: (payload: NotifyPayload) => void;
  setConfig: (patch: Partial<RailWatchConfig>) => void;
  setActivePage: (page: RailWatchPage) => void;
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

export function createRailWatchStore() {
  return createStore<RailWatchStore>((set, get) => ({
    runtime: defaultRuntimeInfo,
    status: defaultStatus,
    config: defaultConfig,
    logs: [],
    pausedLogs: [],
    results: [],
    monitorLoops: 0,
    hits: [],
    notifications: [],
    activePage: "仪表盘",
    logPaused: false,
    eventPanelVisible: true,
    applyRuntimeInfo: (runtime) => {
      set({
        runtime,
        status: runtime.state,
        hits: runtime.state.hits,
      });
    },
    applyRuntimeLabels: (patch) => {
      set({ runtime: { ...get().runtime, ...patch } });
    },
    applyState: (status) => {
      set({
        status,
        hits: status.hits,
      });
    },
    applyLog: (entry) => {
      if (get().logPaused) {
        set({ pausedLogs: [...get().pausedLogs, entry] });
        return;
      }
      set({ logs: [...get().logs, entry] });
    },
    applyResults: (payload) => {
      set({ results: payload.rows, activePage: "购票监控" });
    },
    applyMonitorTick: (payload) => {
      set({ results: payload.rows, monitorLoops: payload.loop });
    },
    applyNotify: (payload) => {
      const nextHits = payload.hit ? [...get().hits, payload.hit] : get().hits;
      set({
        notifications: [...get().notifications, payload],
        hits: nextHits,
      });
    },
    setConfig: (patch) => {
      set({ config: { ...get().config, ...patch } });
    },
    setActivePage: (page) => {
      set({ activePage: page });
    },
    setLogPaused: (paused) => {
      if (!paused && get().pausedLogs.length > 0) {
        set({ logs: [...get().logs, ...get().pausedLogs], pausedLogs: [], logPaused: false });
        return;
      }
      set({ logPaused: paused });
    },
    setEventPanelVisible: (visible) => {
      set({ eventPanelVisible: visible });
    },
    clearLogs: () => {
      set({ logs: [], pausedLogs: [] });
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
