// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { railwatchApi } from "./railwatchApi";
import { useConfirmationBridge, useUpdateReadyPrompt, type ThemedDialog } from "./useThemedDialogs";
import type { ConfirmRequestPayload, UpdateRuntimeState } from "../types";

type ConfirmCaptor = (request: ConfirmRequestPayload) => void;
type UpdateCaptor = (state: UpdateRuntimeState) => void;

let confirmCaptor: ConfirmCaptor | undefined;
let updateCaptor: UpdateCaptor | undefined;
const responded: { id: string; accepted: boolean }[] = [];
const installed: number[] = [];
let showDialog: ReturnType<typeof vi.fn<ThemedDialog>>;

beforeEach(() => {
  confirmCaptor = undefined;
  updateCaptor = undefined;
  responded.length = 0;
  installed.length = 0;
  showDialog = vi.fn<ThemedDialog>().mockResolvedValue(true);
  vi.spyOn(railwatchApi, "onConfirmRequest").mockImplementation((callback) => {
    confirmCaptor = callback;
    return () => undefined;
  });
  vi.spyOn(railwatchApi, "respondConfirmation").mockImplementation((id, accepted) => {
    responded.push({ id, accepted });
  });
  vi.spyOn(railwatchApi, "onUpdateState").mockImplementation((callback) => {
    updateCaptor = callback;
    return () => undefined;
  });
  vi.spyOn(railwatchApi, "command").mockImplementation(async () => ({ state: "idle", run_id: null, operation: null, unresolved_order: false, checked_at: 1 }) as never);
  vi.spyOn(railwatchApi, "installUpdate").mockImplementation(async () => {
    installed.push(1);
    return { ok: true };
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

test("shows a themed dialog for each main-process confirmation and reports the acceptance", async () => {
  const { result } = renderHook(() => useConfirmationBridge(showDialog));
  expect(typeof result.current).toBe("undefined");

  await act(async () => {
    confirmCaptor?.({ id: "confirm-1", title: "清除本地数据", message: "是否继续？" });
  });
  await waitFor(() => expect(showDialog).toHaveBeenCalledTimes(1));
  expect(showDialog).toHaveBeenCalledWith({
    title: "清除本地数据",
    content: "是否继续？",
    okText: "确认",
    cancelText: "取消",
  });

  await act(async () => {
    await Promise.resolve();
  });
  expect(responded).toEqual([{ id: "confirm-1", accepted: true }]);
});

test("queues concurrent confirmations and answers them one by one", async () => {
  let resolveFirst: ((accepted: boolean) => void) | undefined;
  showDialog.mockImplementationOnce(
    () =>
      new Promise<boolean>((resolve) => {
        resolveFirst = resolve;
      }),
  );

  renderHook(() => useConfirmationBridge(showDialog));

  await act(async () => {
    confirmCaptor?.({ id: "confirm-1", title: "t1", message: "m1" });
    confirmCaptor?.({ id: "confirm-2", title: "t2", message: "m2" });
  });
  await waitFor(() => expect(showDialog).toHaveBeenCalledTimes(1));

  await act(async () => {
    resolveFirst?.(false);
    await Promise.resolve();
  });
  await waitFor(() => expect(showDialog).toHaveBeenCalledTimes(2));
  expect(showDialog).toHaveBeenLastCalledWith(
    expect.objectContaining({ title: "t2" }),
  );
  await waitFor(() =>
    expect(responded).toEqual([
      { id: "confirm-1", accepted: false },
      { id: "confirm-2", accepted: true },
    ]),
  );
});

test("uses explicit exit actions and a single acknowledgement for tray notices", async () => {
  renderHook(() => useConfirmationBridge(showDialog));
  await act(async () => {
    confirmCaptor?.({ id: "exit", title: "无法安全退出", message: "任务尚未结束", okText: "强制退出", cancelText: "保留任务", danger: true });
  });
  expect(showDialog).toHaveBeenCalledWith({ title: "无法安全退出", content: "任务尚未结束", okText: "强制退出", cancelText: "保留任务", danger: true });
  await act(async () => {
    confirmCaptor?.({ id: "tray", title: "关闭到托盘", message: "后台继续运行", kind: "info", okText: "知道了" });
  });
  expect(showDialog).toHaveBeenLastCalledWith({ title: "关闭到托盘", content: "后台继续运行", kind: "info", okText: "知道了", cancelText: "取消" });
});

test("declines the active confirmation when the hook unmounts mid-dialog", async () => {
  showDialog.mockImplementationOnce(
    () => new Promise<boolean>(() => undefined),
  );
  const { unmount } = renderHook(() => useConfirmationBridge(showDialog));

  await act(async () => {
    confirmCaptor?.({ id: "confirm-1", title: "t", message: "m" });
  });
  await waitFor(() => expect(showDialog).toHaveBeenCalledTimes(1));

  unmount();
  expect(responded).toEqual([{ id: "confirm-1", accepted: false }]);
});

test("prompts to install once per downloaded version and installs on acceptance", async () => {
  renderHook(() => useUpdateReadyPrompt(showDialog));

  await act(async () => {
    updateCaptor?.({ phase: "downloading", currentVersion: "0.3.6" });
  });
  expect(showDialog).not.toHaveBeenCalled();

  await act(async () => {
    updateCaptor?.({ phase: "downloaded", currentVersion: "0.3.6", latestVersion: "0.3.7" });
  });
  await waitFor(() => expect(showDialog).toHaveBeenCalledTimes(1));
  expect(showDialog).toHaveBeenCalledWith({
    title: "发现新版本",
    content: "RailWatch 12306 0.3.7 已下载完成。是否立即重启安装更新？",
    okText: "立即重启安装",
    cancelText: "稍后",
  });

  await act(async () => {
    updateCaptor?.({ phase: "downloaded", currentVersion: "0.3.6", latestVersion: "0.3.7" });
  });
  expect(showDialog).toHaveBeenCalledTimes(1);
  await waitFor(() => expect(installed).toHaveLength(1));
});

test("does not install again when the user chooses to wait", async () => {
  showDialog.mockResolvedValueOnce(false);
  renderHook(() => useUpdateReadyPrompt(showDialog));

  await act(async () => {
    updateCaptor?.({ phase: "downloaded", currentVersion: "0.3.6", latestVersion: "0.3.7" });
  });
  await waitFor(() => expect(showDialog).toHaveBeenCalledTimes(1));
  expect(installed).toHaveLength(0);
});

test("defers update prompt while a task is active", async () => {
  vi.spyOn(railwatchApi, "command").mockImplementation(async () => ({ state: "busy", run_id: "run", operation: "submitting", unresolved_order: false, checked_at: 1 }) as never);
  renderHook(() => useUpdateReadyPrompt(showDialog));
  await act(async () => { updateCaptor?.({ phase: "downloaded", currentVersion: "0.4.1", latestVersion: "0.4.2" }); });
  expect(showDialog).not.toHaveBeenCalled();
  expect(installed).toHaveLength(0);
});
