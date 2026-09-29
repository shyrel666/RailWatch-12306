export type RailWatchPage = "仪表盘" | "行程设置" | "购票监控" | "订单中心" | "系统设置" | "关于";

export type AppInfo = {
  appVersion: string;
  electronVersion: string;
  chromeVersion: string;
  nodeVersion: string;
  platform: string;
  arch: string;
};

export type RiskLevel = "notice" | "warning" | "active" | "success" | "critical" | string;

export type RailWatchConfig = {
  from_station_cn: string;
  to_station_cn: string;
  date: string;
  train_code: string;
  seat_keyword: string;
  interval: number;
  query_timeout: number;
  query_priority?: "speed" | "reliability";
  request_mode?: "fast" | "balanced" | "conservative" | "legacy";
  auto_submit: boolean;
  seat_prefer: string;
  passenger_count: number;
  prepare_time: number;
  keep_alive: boolean;
  passengers: string;
  passenger_selections?: { name: string; ticket_type: "adult" | "student" | "child" | "unknown"; identity_hint: string }[];
  auto_alternate: boolean;
  alternate_deadline: string;
  date_range: string;
  smart_rate: boolean;
  timer_enabled: boolean;
  target_time: string;
  sale_at?: string;
  sale_time_source?: string;
  sale_time_checked_at?: string;
  burst_window_seconds?: number;
  prewarm_lead_seconds?: number;
  config_version?: number;
  automation_route?: string;
  query_jobs?: RailWatchConfig[];
};

export type NotificationSettings = {
  desktop_urgent: boolean;
  sound_loop: boolean;
  window_attention?: boolean;
  server_chan_enabled: boolean;
  server_chan_key: string;
  server_chan_key_configured?: boolean;
  email_enabled: boolean;
  email_smtp_host: string;
  email_smtp_port: number;
  email_user: string;
  email_password: string;
  email_password_configured?: boolean;
  email_to: string;
  wecom_webhook_enabled: boolean;
  wecom_webhook_url: string;
  wecom_webhook_url_configured?: boolean;
  event_channels: Record<"hit" | "verification" | "payment" | "alternate_active" | "alternate_fulfilled" | "purchase_success", ("server_chan" | "email" | "wecom_webhook")[]>;
};

/** Empty/missing secrets retain their value; null explicitly clears a secret. */
export type NotificationSettingsPatch = Partial<Omit<NotificationSettings,
  "server_chan_key" | "email_password" | "wecom_webhook_url" |
  "server_chan_key_configured" | "email_password_configured" | "wecom_webhook_url_configured"
>> & {
  server_chan_key?: string | null;
  email_password?: string | null;
  wecom_webhook_url?: string | null;
};

export type RailWatchPreferences = {
  theme: "system" | "light" | "dark";
  close_to_tray: boolean;
  auto_rehearsal?: boolean;
  notification_settings: NotificationSettings;
};

/** Existing savePreferences command accepts a partial update, not a replacement. */
export type PreferencesPatch = {
  theme?: RailWatchPreferences["theme"];
  close_to_tray?: boolean;
  auto_rehearsal?: boolean;
  notification_settings?: NotificationSettingsPatch;
};

/** M4 will expose draft save/restore; reading a draft never authorizes execution. */
export type TripDraft = {
  schema_version: 1;
  revision: number;
  saved_at: number; // Unix seconds, as with query and order timestamps.
  config: Partial<RailWatchConfig>;
};

export type TripDraftReadResult =
  | { status: "available"; draft: TripDraft; warning: null }
  | { status: "missing"; draft: null; warning: null }
  | { status: "invalid"; draft: null; warning: string };
export type TripState = { saved_config: RailWatchConfig; saved_at: number | null; draft: TripDraftReadResult };

export type StationSuggestion = { name: string; code: string; pinyin: string; initials: string };
export type StationSearchResult = { items: StationSuggestion[]; warning: string | null };
export type StationSaleSchedule = {
  station_name: string;
  station_code: string;
  sale_time: string;
  start_date: string;
  stop_date: string;
};
export type StationSaleTimes = {
  station: string;
  status: "available" | "not_found" | "stale" | "unavailable";
  schedules: StationSaleSchedule[];
  checked_at: number | null;
  expires_at: number | null;
  retry_at: number;
  source_url: string;
  warning: string | null;
};
export type TripRoute = { from_station: string; to_station: string };
export type TrainFavorite = TripRoute & { trains: string[] };
export type TripChoices = { recent_routes: TripRoute[]; favorites: TrainFavorite[] };
export type PassengerCandidate = { name: string; ticket_type: "adult" | "student" | "child" | "unknown"; identity_hint: string; ambiguous: boolean };
export type PassengerCandidates = { items: PassengerCandidate[]; warning: string | null };

/** M2 contract: a display snapshot, never an authorization to quit/install. */
export type TaskActivity = {
  state: "idle" | "busy" | "unknown";
  run_id: string | null;
  operation: string | null;
  unresolved_order: boolean | null;
  checked_at: number;
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
  human_action?: HumanActionPayload | null;
  activity?: TaskActivity;
  order?: OrderStage;
  task?: { run_id?: string; status?: string; sequence?: number; started_at?: number; target_at?: number | null; next_query_at?: number | null };
  run_id?: string;
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

export type OrderStage = {
  status: string;
  stage?: string;
  label?: string;
  reason?: string;
  order_id?: string;
  updated_at?: number;
  last_checked_at?: number | null;
  observing?: boolean;
  recovery_required?: boolean;
  no_order?: boolean;
  intent?: { intent_id: string; kind: string; train_code: string; date: string; seat: string };
};

/** M5 read models. A missing official ID/time is null, not guessed from history. */
export type OfficialOrderStatus = "pending_payment" | "active" | "fulfilled" | "cancelled" | "expired" | "failed";

export type OrderHistorySummary = {
  intent_id: string;
  order_id: string | null;
  kind: "regular" | "alternate";
  train_code: string;
  date: string;
  from_station: string;
  to_station: string;
  seat: string;
  status: string;
  official_status: OfficialOrderStatus | null;
  official_verified_at: number | null;
  updated_at: number;
  last_checked_at: number | null;
  last_check_status?: string | null;
  observing: boolean;
  recovery_required: boolean;
};

export type OrderTimelineEvent = {
  sequence: number;
  at: number;
  stage: string;
  scope: "local" | "official";
  message: string;
};

export type OrderHistoryPage = {
  items: OrderHistorySummary[];
  next_cursor: string | null;
};

export type OrderHistoryDetail = {
  events_truncated?: boolean;
  summary: OrderHistorySummary;
  events: OrderTimelineEvent[];
  history_complete: boolean;
};

export type RuntimeInfo = {
  date_policy?: { presale_window_days: number; timezone: string };
  seat_capabilities?: { name: string; query: boolean; regular: boolean; alternate: boolean }[];
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
  id?: number;
  run_id?: string;
  time: string;
  level: string;
  message: string;
};

export type QueryResultRow = {
  date?: string;
  train: string;
  raw: string;
};

export type SeatAvailability = {
  status: "available" | "unavailable" | "alternate" | "unknown" | "not_applicable";
  count: number | null;
  raw: string;
};

export type QueryConditions = {
  from_station: string;
  to_station: string;
  date: string;
  train_codes: string[];
  seat_types: string[];
};

/** M1 structured row; current legacy rows remain valid until M1 is wired up. */
export type StructuredQueryResultRow = QueryResultRow & {
  date: string;
  from_station: string | null;
  to_station: string | null;
  departure_time: string | null;
  arrival_time: string | null;
  arrival_day_offset: number | null;
  seats: Record<string, SeatAvailability>;
};

/** One snapshot per query date, including successful empty results. */
export type QueryAttempt = {
  run_id: string | null;
  request_id?: string;
  query_id: string;
  sequence: number;
  conditions: QueryConditions;
  started_at: number;
};

export type QuerySnapshot = {
  schema_version: 1;
  run_id: string | null;
  query_id: string;
  sequence: number;
  conditions: QueryConditions;
  completed_at: number;
  fetched_at: number | null;
  status: "success" | "error";
  error: string | null;
  rows: StructuredQueryResultRow[];
};

export type ResultsPayload = {
  request_id?: string;
  snapshots?: QuerySnapshot[];
  run_id?: string;
  query_id?: string;
  fetched_at?: number;
  conditions?: unknown;
  rows: QueryResultRow[];
};

export type MonitorTickPayload = {
  snapshot?: QuerySnapshot;
  run_id?: string;
  query_id?: string;
  fetched_at?: number | null;
  conditions?: unknown;
  loop: number;
  date: string;
  rows: QueryResultRow[];
};

export type NotifyPayload = {
  run_id?: string;
  title: string;
  message: string;
  hit?: TicketHit;
  priority?: "urgent" | "normal" | string;
};

export type HumanActionPayload = {
  event_id?: string;
  run_id?: string;
  title: string;
  message: string;
  train_code?: string;
  priority?: "urgent" | "normal" | string;
};

export type BridgeEvent =
  | { event: "queryStarted"; payload: QueryAttempt }
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

export type ConfirmRequestPayload = {
  id: string;
  title: string;
  message: string;
  okText?: string;
  cancelText?: string;
  kind?: "confirm" | "info";
  danger?: boolean;
};

export type ExportLocation = { name: string; path: string };
export type ExportLocations = { directory: string; fileName: string; shortcuts: ExportLocation[] };
export type ExportDirectory = { directory: string; parent: string; folders: ExportLocation[]; files: string[] };

export type { RehearsalCheck, RehearsalReport, RunReviewSummary, RunReviewDetail } from "./lib/rehearsal";
