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
): NextAction {
  if (hasUnresolvedOrder(status.order))
    return {
      title:
        status.order!.label ||
        taskLabels[status.order!.stage || status.order!.status] ||
        "订单待核对",
      description:
        status.order!.reason || "请查看订单状态，在官方页面完成支付或核验。",
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
  if (status.error_message)
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
      title: "先为出发做好准备",
      description: "检查运行环境，确认浏览器与必要组件已经就绪。",
      label: "检查环境",
      page: "系统设置",
      section: "settings-environment",
      tone: "normal",
    };
  if (!status.login_ready)
    return {
      title: "登录后，继续你的行程",
      description: "打开 12306，在官方页面完成登录与身份核验。",
      label: "前往登录",
      page: "系统设置",
      section: "settings-login",
      tone: "normal",
    };
  if (!tripValid || !status.query_ready)
    return {
      title: "确认你的出行安排",
      description: "完善路线、日期与乘客，查询余票后核对结果。",
      label: "完善行程",
      page: "行程设置",
      section: "trip-basics",
      tone: "normal",
    };
  return {
    title: "一切就绪，准备出发",
    description: "你的行程已经准备好，进入监控页开始关注余票变化。",
    label: "进入购票监控",
    page: "购票监控",
    section: "monitor-controls",
    tone: "normal",
  };
}
