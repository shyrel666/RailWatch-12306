import policies from "../../railwatch_policies/date_strategies.json";
import type { RailWatchConfig } from "../types";

export const DATE_STRATEGIES = policies.strategies;
export type DateStrategy = keyof typeof DATE_STRATEGIES;
export const DATE_SCAN_BUDGET = policies;
export const DEFAULT_DATE_STRATEGY = {
  date_strategy: policies.default as DateStrategy,
  date_scan_budget_seconds: policies.scan_budget_seconds,
};

export function dateStrategy(config: RailWatchConfig): DateStrategy {
  return config.date_strategy && Object.hasOwn(DATE_STRATEGIES, config.date_strategy)
    ? config.date_strategy : DEFAULT_DATE_STRATEGY.date_strategy;
}

export function dateStrategySummary(config: RailWatchConfig): string {
  if (config.date_range === "单日") return "仅查询所选日期，本日先检查全部目标现票，再检查候补。";
  const policy = dateStrategy(config);
  const budget = policy === "inventory_first"
    ? ` 扫描预算${config.date_scan_budget_seconds ?? policies.scan_budget_seconds}秒；预算不截断查询、官方等待或提交前重查。` : "";
  const timing = config.timer_enabled
    ? ` 起售窗口内集中查询所选日期，起售后${config.burst_window_seconds ?? 45}秒再应用多日期策略；明确售罄的候补回退仍核对原日期。` : "";
  return DATE_STRATEGIES[policy].description + budget + timing;
}
