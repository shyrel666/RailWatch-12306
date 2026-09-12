import { useEffect, useRef, useState } from "react";
import { railwatchApi } from "./railwatchApi";
import type { ConfirmRequestPayload, UpdateRuntimeState } from "../types";

export type ThemedDialogOptions = {
  title: string;
  content: string;
  okText: string;
  cancelText: string;
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
      okText: "确认",
      cancelText: "取消",
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
 * 更新包下载完成后，用主题化对话框替代原生的"是否立即重启安装"系统弹窗；
 * 每个版本只提示一次，用户选"稍后"仍可从状态栏的更新按钮安装。
 */
export function useUpdateReadyPrompt(showDialog: ThemedDialog): void {
  const promptedVersionRef = useRef<string | null>(null);

  useEffect(() => {
    return railwatchApi.onUpdateState((state) => {
      const payload = state as UpdateRuntimeState | undefined;
      if (!payload || payload.phase !== "downloaded" || !payload.latestVersion) {
        return;
      }
      if (promptedVersionRef.current === payload.latestVersion) {
        return;
      }
      promptedVersionRef.current = payload.latestVersion;
      void showDialog({
        title: "发现新版本",
        content: `RailWatch 12306 ${payload.latestVersion} 已下载完成。是否立即重启安装更新？`,
        okText: "立即重启安装",
        cancelText: "稍后",
      })
        .then((accepted) => {
          if (accepted) {
            void railwatchApi.installUpdate();
          }
        })
        .catch(() => undefined);
    });
  }, [showDialog]);
}
