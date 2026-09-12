import policies from "../../railwatch_policies/query_strategies.json";
import type { RailWatchConfig } from "../types";

export type QueryPriority = keyof typeof policies.priorities;
export type RequestMode = keyof typeof policies.modes;
export const REQUEST_MODES = policies.modes;
export const PRIORITIES = policies.priorities;

export function modeDefaults(mode: RequestMode): Partial<RailWatchConfig> {
  const preset = REQUEST_MODES[mode];
  return { request_mode: mode, interval: preset.interval, query_timeout: preset.query_timeout,
    smart_rate: true, keep_alive: true };
}

export function priorityDefaults(priority: QueryPriority): Partial<RailWatchConfig> {
  return { ...modeDefaults(PRIORITIES[priority].request_mode as RequestMode), query_priority: priority };
}

export const DEFAULT_QUERY_STRATEGY = priorityDefaults(policies.default_priority as QueryPriority);

export function queryPriority(config: RailWatchConfig): QueryPriority {
  return config.query_priority ?? (requestMode(config) === "fast" ||
    (requestMode(config) === "legacy" && config.smart_rate && config.interval <= 4) ? "speed" : "reliability");
}

export function requestMode(config: RailWatchConfig): RequestMode {
  return config.request_mode ?? "legacy";
}

export function isStrategyCustomized(config: RailWatchConfig): boolean {
  const preset = priorityDefaults(queryPriority(config));
  return Object.entries(preset).some(([key, value]) => config[key as keyof RailWatchConfig] !== value);
}

export function delayPreview(config: RailWatchConfig) {
  const mode = REQUEST_MODES[requestMode(config)];
  const base = config.smart_rate ? Math.max(mode.min_interval, config.interval) : config.interval;
  const cap = Math.max(mode.max_interval, base);
  const low = config.smart_rate ? Math.max(mode.min_interval, base * 0.8) : base * 0.7;
  const high = config.smart_rate ? Math.min(cap, base * 1.2) : base * 1.3;
  return { label: `${low.toFixed(1)} ~ ${high.toFixed(1)}`,
    detail: config.smart_rate
      ? `初始等待范围；智能轮询将在 ${mode.min_interval} ~ ${cap} 秒内调整，异常时自动放慢。`
      : "智能轮询已关闭：按基础间隔 ±30% 随机等待，不使用自适应退避。" };
}
