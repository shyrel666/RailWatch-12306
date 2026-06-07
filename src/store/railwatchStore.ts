import { createStore } from "zustand/vanilla";
import type {
  LogEntry,
  NotifyPayload,
  QueryResultRow,
  RailWatchConfig,
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
  app_slug: "railwatch-12306",
  pages: ["仪表盘", "行程设置", "监控", "设置"],
  data_dir: "",
  chromedriver_path: "",
  chrome_version: "未知",
  core_available: false,
  core_import_error: "",
  selenium_available: false,
  chromedriver_manager_available: false,
  state: defaultStatus,
};

export const defaultConfig: RailWatchConfig = {
  from_station_cn: "北京",
  to_station_cn: "上海",
  date: "",
  train_code: "",
  seat_keyword: "",
  interval: 5,
  auto_submit: false,
  seat_prefer: "无偏好",
  passenger_count: 1,
  prepare_time: 2,
  keep_alive: true,
  passengers: "",
  auto_alternate: false,
  alternate_deadline: "18:00",
  smart_rate: true,
  timer_enabled: false,
  target_time: "00:00:00",
};

export type RailWatchStore = {
  runtime: RuntimeInfo;
  status: RailWatchStatus;
  config: RailWatchConfig;
  logs: LogEntry[];
  results: QueryResultRow[];
  hits: TicketHit[];
  notifications: NotifyPayload[];
  activePage: string;
  logPaused: boolean;
  eventPanelVisible: boolean;
  applyRuntimeInfo: (runtime: RuntimeInfo) => void;
  applyState: (status: RailWatchStatus) => void;
  applyLog: (entry: LogEntry) => void;
  applyResults: (payload: ResultsPayload) => void;
  applyNotify: (payload: NotifyPayload) => void;
  setConfig: (patch: Partial<RailWatchConfig>) => void;
  setActivePage: (page: string) => void;
  setLogPaused: (paused: boolean) => void;
  setEventPanelVisible: (visible: boolean) => void;
  clearLogs: () => void;
  errorCount: () => number;
  filteredLogs: (filter: string) => LogEntry[];
};

const logLevelByFilter: Record<string, string> = {
  信息: "INFO",
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
    results: [],
    hits: [],
    notifications: [],
    activePage: "仪表盘",
    logPaused: false,
    eventPanelVisible: true,
    applyRuntimeInfo: (runtime) => {
      set({
        runtime,
        status: runtime.state,
      });
    },
    applyState: (status) => {
      set({
        status,
        hits: status.hits.length ? status.hits : get().hits,
      });
    },
    applyLog: (entry) => {
      set({ logs: [...get().logs, entry] });
    },
    applyResults: (payload) => {
      set({ results: payload.rows, activePage: "监控" });
    },
    applyNotify: (payload) => {
      const nextHits = payload.hit ? [...get().hits, payload.hit] : get().hits;
      set({
        notifications: [...get().notifications, payload],
        hits: nextHits,
        activePage: "仪表盘",
      });
    },
    setConfig: (patch) => {
      set({ config: { ...get().config, ...patch } });
    },
    setActivePage: (page) => {
      set({ activePage: page });
    },
    setLogPaused: (paused) => {
      set({ logPaused: paused });
    },
    setEventPanelVisible: (visible) => {
      set({ eventPanelVisible: visible });
    },
    clearLogs: () => {
      set({ logs: [] });
    },
    errorCount: () => get().logs.filter((entry) => entry.level === "ERROR").length,
    filteredLogs: (filter) => {
      const level = logLevelByFilter[filter];
      return level ? get().logs.filter((entry) => entry.level === level) : get().logs;
    },
  }));
}

export const railwatchStore = createRailWatchStore();
