export type RailWatchPage = "仪表盘" | "行程设置" | "购票监控" | "系统设置";

export type RiskLevel = "notice" | "warning" | "active" | "success" | "critical" | string;

export type RailWatchConfig = {
  from_station_cn: string;
  to_station_cn: string;
  date: string;
  train_code: string;
  seat_keyword: string;
  interval: number;
  auto_submit: boolean;
  seat_prefer: string;
  passenger_count: number;
  prepare_time: number;
  keep_alive: boolean;
  passengers: string;
  auto_alternate: boolean;
  alternate_deadline: string;
  date_range: string;
  smart_rate: boolean;
  timer_enabled: boolean;
  target_time: string;
};

export type TicketHit = {
  train_code: string;
  seat_type: string;
  status: string;
  source: string;
  detail: string;
  label: string;
};

export type RailWatchStatus = {
  phase: string;
  environment_ready: boolean;
  login_ready: boolean;
  query_ready: boolean;
  monitoring: boolean;
  auto_submit_enabled: boolean;
  auto_alternate_enabled: boolean;
  risk_level: RiskLevel;
  status_message: string;
  error_message: string;
  current_config: Record<string, unknown>;
  hits: TicketHit[];
  summary: string;
};

export type RuntimeInfo = {
  app_display_name: string;
  app_version: string;
  app_slug: string;
  pages: string[];
  data_dir: string;
  data_dir_writable: boolean;
  data_dir_free_bytes: number;
  chromedriver_path: string;
  chrome_version: string;
  core_available: boolean;
  core_import_error: string;
  selenium_available: boolean;
  chromedriver_manager_available: boolean;
  network_ok: boolean;
  network_label: string;
  railway_ok: boolean;
  railway_label: string;
  proxy_configured: boolean;
  proxy_label: string;
  proxy_value: string;
  state: RailWatchStatus;
};

export type LogEntry = {
  time: string;
  level: string;
  message: string;
};

export type QueryResultRow = {
  train: string;
  raw: string;
};

export type ResultsPayload = {
  rows: QueryResultRow[];
};

export type NotifyPayload = {
  title: string;
  message: string;
  hit?: TicketHit;
};

export type BridgeEvent =
  | { event: "log"; payload: LogEntry }
  | { event: "state"; payload: RailWatchStatus }
  | { event: "results"; payload: ResultsPayload }
  | { event: "notify"; payload: NotifyPayload }
  | { event: "labels"; payload: { chromedriver_path?: string; chrome_version?: string } }
  | { event: string; payload: unknown };

export type ConfirmationRequest = {
  requires_confirmation: true;
  title: string;
  message: string;
};
