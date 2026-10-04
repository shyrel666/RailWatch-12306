import policy from "../../railwatch_policies/order_policies.json";
import type { RailWatchConfig } from "../types";

export const ORDER_POLICY = policy;
export const DEFAULT_ORDER_POLICY = {
  alternate_mode: policy.alternate_mode as "single" | "multiple",
  alternate_max_combinations: policy.alternate_max_combinations,
  order_watch_enabled: policy.order_watch_enabled,
  order_watch_interval_seconds: policy.order_watch_interval_seconds,
};

export function orderPolicySummary(config: RailWatchConfig) {
  const alternate = config.alternate_mode === "multiple"
    ? `多组合候补：最多${config.alternate_max_combinations ?? policy.alternate_max_combinations}个组合、${policy.max_dates}个日期，仅选择已配置的车次和席别。`
    : "候补采用首个可用组合。";
  const observation = (config.order_watch_enabled ?? policy.order_watch_enabled)
    ? `取得订单号后持续核对，候补生效后每${config.order_watch_interval_seconds ?? policy.order_watch_interval_seconds}秒核对一次；异常时放慢，可随时停止。`
    : "持续订单核对已关闭，仍会短时观察付款页面。";
  return alternate + observation;
}
