import { useEffect, useRef, useState } from "react";
import { railwatchApi } from "./railwatchApi";
import type { ConfirmRequestPayload, UpdateRuntimeState } from "../types";

export type ThemedDialogOptions = {
  title: string;
  content: string;
  okText: string;
  cancelText: string;
  kind?: "confirm" | "info";
  danger?: boolean;
};

export type ThemedDialog = (options: ThemedDialogOptions) => Promise<boolean>;

/**
 * 主进程发起的确认请求（如清除本地数据、关闭浏览器）不再使用原生系统弹窗，
 * 而是排队交给渲染层的主题化对话框展示，并把用户选择回传给主进程的确认闸门。
 */
export function useConfirmationBridge(showDialog: ThemedDialog): void {
  const [queue, setQueue] = useState<ConfirmRequestPayload[]>([]);

  useEffect(() => {
    return railwatchApi.onConfirmRequest((request) => {
      if (request && typeof request.id === "string" && typeof request.title === "string") {
        setQueue((current) => [...current, request]);
      }
    });
  }, []);

  const active = queue[0];

  useEffect(() => {
    if (!active) {
      return undefined;
    }
    let settled = false;
    void showDialog({
      title: active.title,
      content: active.message,
      okText: active.okText ?? "确认",
      cancelText: active.cancelText ?? "取消",
      ...(active.kind ? { kind: active.kind } : {}),
      ...(active.danger !== undefined ? { danger: active.danger } : {}),
    })
      .then((accepted) => {
        settled = true;
        railwatchApi.respondConfirmation(active.id, accepted);
      })
      .catch(() => {
        settled = true;
        railwatchApi.respondConfirmation(active.id, false);
      })
      .finally(() => {
        setQueue((current) => current.filter((item) => item.id !== active.id));
      });
    return () => {
      if (!settled) {
        // 组件卸载时兜底拒绝，避免主进程一直等待这次确认。
        railwatchApi.respondConfirmation(active.id, false);
      }
    };
  }, [active, showDialog]);
}

/**
 * 更新包下载完成且当前没有活动任务或未完成订单时，打开更新面板。
 * 每个版本只自动展示一次，安装由面板中的显式操作触发。
 */
export function useUpdateReadyPrompt(showUpdate: (state: UpdateRuntimeState) => void, enabled = true): void {
  const promptedVersionsRef = useRef(new Set<string>());
  const showUpdateRef = useRef(showUpdate);

  useEffect(() => {
    showUpdateRef.current = showUpdate;
  }, [showUpdate]);

  useEffect(() => {
    let active = true;
    let latestState: UpdateRuntimeState | undefined;
    if (!enabled) return;
    const checkingVersions = new Set<string>();
    const unsubscribe = railwatchApi.onUpdateState((state) => {
      const payload = state as UpdateRuntimeState | undefined;
      latestState = payload;
      if (!active || !payload || payload.phase !== "downloaded" || !payload.latestVersion) {
        return;
      }
      const version = payload.latestVersion;
      if (promptedVersionsRef.current.has(version) || checkingVersions.has(version)) {
        return;
      }
      checkingVersions.add(version);
      void railwatchApi.command<import("../types").TaskActivity>("taskActivity").then((activity) => {
        if (!active || activity.state !== "idle" || activity.unresolved_order ||
          latestState?.phase !== "downloaded" || latestState.latestVersion !== version ||
          promptedVersionsRef.current.has(version)) return;
        promptedVersionsRef.current.add(version);
        showUpdateRef.current(latestState);
      }).catch(() => undefined).finally(() => {
        checkingVersions.delete(version);
      });
    });
    return () => {
      active = false;
      unsubscribe();
    };
  }, [enabled]);
}
