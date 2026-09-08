import type { RailWatchConfig, RailWatchStatus } from "../types";

export function displayedConfig(config: RailWatchConfig, status: RailWatchStatus): RailWatchConfig {
  return status.monitoring ? { ...config, ...status.current_config } : config;
}

export const taskLabels: Record<string, string> = {
  preparing: "准备监控", waiting: "等待定时启动", querying: "查询中", backoff: "等待下一次查询",
  stopping: "正在停止", stopped: "监控已停止", human_action: "需要人工处理", hit: "已命中", error: "监控异常",
  reconciling: "核对原订单", submitting: "正在提交", pending_payment: "预订待支付",
  alternate_pending_payment: "候补待支付", active: "候补已生效", fulfilled: "购票成功",
  unknown: "订单结果待核对", verification: "需要核验", not_submitted: "未提交",
  cancelled: "订单已取消", expired: "订单已过期", failed: "候补兑现失败", sold_out: "已确认售罄",
};
