import type { RailWatchConfig, RailWatchStatus } from "../types";

export function displayedConfig(config: RailWatchConfig, status: RailWatchStatus): RailWatchConfig {
  return status.monitoring ? { ...config, ...status.current_config } : config;
}

export const taskLabels: Record<string, string> = {
  preparing: "准备监控", waiting: "等待定时启动", querying: "查询中", backoff: "等待下一次查询",
  stopping: "正在停止", stopped: "监控已停止", human_action: "需要人工处理", hit: "已命中", error: "监控异常",
};
