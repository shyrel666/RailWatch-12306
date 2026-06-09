export type RailWatchPage = "仪表盘" | "行程设置" | "购票监控" | "系统设置";

export type RiskLevel = "notice" | "warning" | "active" | "success" | "critical" | string;

export type RailWatchConfig = {
  from_station_cn: string;
  to_station_cn: string;
  date: string;
  train_code: string;
  seat_keyword: string;
  interval: number;
  query_timeout: number;
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
  burst_window_seconds?: number;
  prewarm_lead_seconds?: number;
  config_version?: number;
  automation_route?: string;
  query_jobs?: RailWatchConfig[];
};

export type NotificationSettings = {
  desktop_urgent: boolean;
  sound_loop: boolean;
  server_chan_enabled: boolean;
  server_chan_key: string;
  email_enabled: boolean;
  email_smtp_host: string;
  email_smtp_port: number;
  email_user: string;
  email_password: string;
  email_to: string;
  wecom_webhook_enabled: boolean;
  wecom_webhook_url: string;
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
  automation_route?: string;
  server_time_offset_seconds?: number;
  server_time_last_error?: string;
  notification_settings?: NotificationSettings;
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

export type MonitorTickPayload = {
  loop: number;
  date: string;
  rows: QueryResultRow[];
};

export type NotifyPayload = {
  title: string;
  message: string;
  hit?: TicketHit;
  priority?: "urgent" | "normal" | string;
};

export type HumanActionPayload = {
  title: string;
  message: string;
  train_code?: string;
  priority?: "urgent" | "normal" | string;
};

export type BridgeEvent =
  | { event: "log"; payload: LogEntry }
  | { event: "state"; payload: RailWatchStatus }
  | { event: "results"; payload: ResultsPayload }
  | { event: "notify"; payload: NotifyPayload }
  | { event: "humanAction"; payload: HumanActionPayload }
  | { event: "monitorTick"; payload: MonitorTickPayload }
  | { event: "labels"; payload: { chromedriver_path?: string; chrome_version?: string } }
  | { event: string; payload: unknown };

export type ConfirmationRequest = {
  requires_confirmation: true;
  title: string;
  message: string;
};

export type UpdateAsset = {
  name: string;
  url: string;
  size: number;
  sha256?: string;
};

export type UpdateCheckSuccess = {
  ok: true;
  currentVersion: string;
  latestVersion: string;
  hasUpdate: boolean;
  releaseName: string;
  releaseNotes: string;
  publishedAt: string;
  releaseUrl: string;
  assets: UpdateAsset[];
  cached?: boolean;
  stale?: boolean;
  warning?: string;
  source?: "api" | "manifest" | "redirect" | "cache" | "stale-cache" | "updater";
};

export type UpdateCheckFailure = {
  ok: false;
  currentVersion: string;
  error: string;
  code: "network" | "parse" | "no-assets" | "rate-limit" | "unknown";
};

export type UpdateCheckResult = UpdateCheckSuccess | UpdateCheckFailure;

export type UpdatePhase =
  | "idle"
  | "checking"
  | "available"
  | "downloading"
  | "downloaded"
  | "not-available"
  | "error";

export type UpdateRuntimeState = {
  phase: UpdatePhase;
  currentVersion: string;
  latestVersion?: string;
  releaseNotes?: string;
  downloadPercent?: number;
  error?: string;
  result?: UpdateCheckResult;
};
