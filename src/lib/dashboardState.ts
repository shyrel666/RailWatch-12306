import type {
  HumanActionPayload,
  OrderStage,
  RailWatchPage,
  RailWatchStatus,
} from "../types";
import { taskLabels } from "./taskDisplay";

export function hasUnresolvedOrder(order?: OrderStage) {
  return Boolean(
    order?.status &&
      (order.recovery_required ||
        (["not_submitted", "sold_out"].includes(order.status)
          ? !order.no_order
          : !["fulfilled", "cancelled", "expired", "failed"].includes(
              order.status,
            ))),
  );
}

/**
 * Why a manual browser task (a query, reading passengers) cannot run now. The runtime refuses the
 * same cases: monitoring owns the browser, and a pending order keeps its page for the user.
 */
export function browserTaskBlock(monitoring: boolean, order: OrderStage | undefined, action: string) {
  if (monitoring) return `监控运行中，请停止监控后${action}。`;
  if (hasUnresolvedOrder(order)) return `有待支付或待核对的订单，受控浏览器需留给订单页，请先处理订单再${action}。`;
  return "";
}

export function hasSetupWarning(status: RailWatchStatus) {
  return Boolean(
    status.error_message &&
      status.risk_level === "warning" &&
      !status.monitoring &&
      (!status.environment_ready || !status.login_ready),
  );
}

export type NextAction = {
  title: string;
  description: string;
  label: string;
  page: RailWatchPage;
  section: string;
  tone: "normal" | "warning" | "active";
};
export function dashboardAction(
  status: RailWatchStatus,
  human: HumanActionPayload | null,
  tripValid: boolean,
  rehearsalNeeded = false,
): NextAction {
  if (hasUnresolvedOrder(status.order))
    return {
      title:
        status.order!.label ||
        taskLabels[status.order!.stage || status.order!.status] ||
        "订单待核对",
      description:
        status.order!.reason || "请在官方页面完成支付或核验。",
      label: "查看并处理订单",
      page: "购票监控",
      section: "monitor-attention",
      tone: "warning",
    };
  if (human)
    return {
      title: human.title,
      description: human.message,
      label: "查看处理要求",
      page: "购票监控",
      section: "monitor-human",
      tone: "warning",
    };
  if (status.monitoring)
    return {
      title: taskLabels[status.task?.status || ""] || "监控运行中",
      description: status.status_message,
      label: "查看购票监控",
      page: "购票监控",
      section: "monitor-controls",
      tone: "active",
    };
  const setupWarning = hasSetupWarning(status);
  if (status.error_message && !setupWarning)
    return {
      title: "需要关注运行状态",
      description: status.error_message,
      label: "查看运行详情",
      page: "购票监控",
      section: "monitor-controls",
      tone: "warning",
    };
  if (!status.environment_ready)
    return {
      title: "检查运行环境",
      description: setupWarning
        ? "请先检查运行环境，再打开 12306 登录页面。"
        : "确认 Chrome、驱动与运行组件可用。",
      label: "检查环境",
      page: "系统设置",
      section: "settings-environment",
      tone: setupWarning ? "warning" : "normal",
    };
  if (!status.login_ready)
    return {
      title: "登录 12306",
      description: setupWarning
        ? status.error_message
        : "在官方页面完成登录，之后即可查询与下单。",
      label: "前往登录",
      page: "系统设置",
      section: "settings-login",
      tone: setupWarning ? "warning" : "normal",
    };
  if (!tripValid || !status.query_ready)
    return {
      title: "完善你的行程",
      description: "填写路线、日期与乘客，并查询一次余票。",
      label: "完善行程",
      page: "行程设置",
      section: "trip-basics",
      tone: "normal",
    };
  if (rehearsalNeeded) return { title: "开售前先彩排一次", description: "提前检查登录、乘客与下单路径。",
    label: "前往起售彩排", page: "购票监控", section: "monitor-rehearsal", tone: "normal" };
  return {
    title: "一切就绪",
    description: "行程已准备好，可以开始监控余票。",
    label: "进入购票监控",
    page: "购票监控",
    section: "monitor-controls",
    tone: "normal",
  };
}
