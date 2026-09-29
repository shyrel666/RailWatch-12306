import type { RailWatchConfig, RuntimeInfo } from "../types";

// Check order mirrors RailWatchBridge.start_monitor; the shared cases in
// tests/fixtures/automation-readiness-cases.json pin both implementations.
export function automationConfigIssue(
  config: RailWatchConfig,
  capabilities?: RuntimeInfo["seat_capabilities"],
): string | null {
  if (!config.auto_submit && !config.auto_alternate) return null;
  if (!config.train_code.trim()) return "自动化需要明确的目标车次，请在行程设置中选择车次。";
  const names = config.passengers.split(/[,，、]+/).map(name => name.trim()).filter(Boolean);
  if (!names.length) return "自动化需要乘车人姓名，请在行程设置中添加乘客。";
  if (new Set(names).size !== names.length) return "乘车人姓名重复，请在行程设置中删除重复乘客。";
  if (config.passenger_selections?.some(item => !names.includes(item.name) || item.ticket_type !== "adult")) {
    return "自动交易仅支持已核对为成人的乘客；学生、儿童和未知票种请在官方页面处理。";
  }
  if (config.auto_alternate && names.length > 19) return "候补单最多支持19名乘车人。";
  const seats = config.seat_keyword.split(/[,，、;；\s]+/).filter(Boolean);
  if (!seats.length || seats.includes("不限")) {
    return "已启用自动化，请选择明确席别，不能使用“不限”；仅监控余票可关闭自动提交和自动候补。";
  }
  if (capabilities) {
    for (const name of seats) {
      const seat = capabilities.find(item => item.name === name);
      if (!seat || (config.auto_submit && !seat.regular) || (config.auto_alternate && !seat.alternate)) {
        return `席别 ${name} 不支持当前启用的自动化方式，请更换席别或关闭对应自动化。`;
      }
    }
  }
  return null;
}
