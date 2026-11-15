// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { EnvironmentProgress } from "../types";
import { EnvironmentProgressDialog } from "./EnvironmentProgressDialog";

const start = new Date("2026-11-15T05:00:00Z").getTime() / 1000;
const progress: EnvironmentProgress = {
  operation: "checkEnvironment", status: "running", started_at: start, updated_at: start,
  stage: "downloading", message: "正在下载匹配的 ChromeDriver", source: "npmmirror 镜像",
  downloaded_bytes: 2 * 1024 * 1024, total_bytes: 8 * 1024 * 1024,
  bytes_per_second: 256 * 1024, eta_seconds: 24,
};

beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(start * 1000); });
afterEach(() => { cleanup(); vi.useRealTimers(); });

function metric(label: string) {
  return screen.getByText(label, { selector: "dt" }).nextElementSibling?.textContent;
}

test("shows actual bytes, percentage, speed and a download-only estimate", () => {
  const close = vi.fn();
  render(<EnvironmentProgressDialog progress={progress} open onClose={close} />);
  expect(screen.getByRole("dialog").textContent).toContain("环境检查");
  expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("25");
  expect(screen.getByText("2.0 MB / 8.0 MB")).toBeTruthy();
  expect(screen.getByText("256.0 KB/s")).toBeTruthy();
  expect(metric("预计下载剩余")).toBe("约 24 秒");
  expect(screen.getByText("下载完成后，将自动安装并验证浏览器。")).toBeTruthy();
  expect(screen.getByText("npmmirror 镜像")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "收起" }));
  expect(close).toHaveBeenCalledTimes(1);
});

test.each([
  ["downloading", "下载"], ["resolving", "读取"],
] as const)("unknown %s size prominently shows transferred bytes without a fabricated percentage or ETA", (stage, verb) => {
  render(<EnvironmentProgressDialog progress={{ ...progress, stage, total_bytes: null, downloaded_bytes: 12 * 1024 * 1024 }} open onClose={vi.fn()} />);
  expect(screen.getByText("12.0 MB").textContent).toBe(`12.0 MB已${verb}`);
  expect(screen.getByRole("progressbar").getAttribute("aria-valuetext")).toBe(`已${verb} 12.0 MB，总大小未知`);
  expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBeNull();
  expect(metric("文件大小")).toBe("总大小未知");
  expect(metric(`预计${verb}剩余`)).toBe("暂无法估算");
  expect(screen.queryByText("%", { selector: "small" })).toBeNull();
  expect(screen.queryByText("约 24 秒")).toBeNull();
});

test("streaming version information shows reading progress separately from driver download", () => {
  const view = render(<EnvironmentProgressDialog progress={{ ...progress, stage: "resolving",
    message: "正在读取可用版本信息" }} open onClose={vi.fn()} />);
  expect(screen.getByRole("progressbar", { name: "版本信息读取进度" }).getAttribute("aria-valuenow")).toBe("25");
  expect(screen.getByText("256.0 KB/s")).toBeTruthy();
  expect(metric("预计读取剩余")).toBe("约 24 秒");
  expect(screen.queryByText("预计下载剩余")).toBeNull();
  expect(screen.getByRole("heading", { name: "正在读取版本信息" })).toBeTruthy();
  expect(screen.getByText("查找与本机 Chrome 匹配的驱动。")).toBeTruthy();
  view.rerender(<EnvironmentProgressDialog progress={{ ...progress, stage: "resolving",
    total_bytes: null, message: "正在读取可用版本信息" }} open onClose={vi.fn()} />);
  expect(screen.getByText("2.0 MB").textContent).toBe("2.0 MB已读取");
  expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBeNull();
  expect(metric("预计读取剩余")).toBe("暂无法估算");
  expect(screen.queryByText("约 24 秒")).toBeNull();
});

test("elapsed time advances without backend events and stale speed estimates disappear", () => {
  render(<EnvironmentProgressDialog progress={progress} open onClose={vi.fn()} />);
  act(() => vi.advanceTimersByTime(15000));
  expect(screen.getByText("已用 15 秒")).toBeTruthy();
  expect(screen.getByText("等待网络响应")).toBeTruthy();
  expect(screen.queryByText("256.0 KB/s")).toBeNull();
  expect(metric("预计下载剩余")).toBe("暂无法估算");
  expect(screen.queryByText("约 24 秒")).toBeNull();
  expect(screen.getByText("暂未收到新数据，传输恢复后更新。")).toBeTruthy();
  act(() => vi.advanceTimersByTime(16000));
  expect(screen.getByText("已用 31 秒")).toBeTruthy();
});

test("switching stages removes the previous download metrics", () => {
  const view = render(<EnvironmentProgressDialog progress={progress} open onClose={vi.fn()} />);
  view.rerender(<EnvironmentProgressDialog progress={{ ...progress, stage: "retrying", message: "正在尝试官方源" }} open onClose={vi.fn()} />);
  expect(screen.getByRole("heading", { name: "正在切换下载源" })).toBeTruthy();
  expect(screen.getByText("正在尝试官方源")).toBeTruthy();
  expect(screen.queryByRole("progressbar")).toBeNull();
  expect(screen.queryByText("预计下载剩余")).toBeNull();
  expect(screen.queryByText("256.0 KB/s")).toBeNull();
});

test.each([
  ["checkEnvironment", "环境已就绪", "可以继续登录 12306，准备查询余票。"],
  ["downloadChromeDriver", "驱动已安装", "现在可以检查运行环境。"],
] as const)("%s completion has the right next step and freezes elapsed time", (operation, heading, nextStep) => {
  render(<EnvironmentProgressDialog progress={{ ...progress, operation, status: "success", stage: "complete",
    updated_at: start + 83, message: "准备完成" }} open onClose={vi.fn()} />);
  act(() => vi.advanceTimersByTime(120000));
  expect(screen.getByRole("heading", { name: heading })).toBeTruthy();
  expect(screen.getByText(nextStep)).toBeTruthy();
  expect(screen.queryByRole("heading", { name: operation === "checkEnvironment" ? "驱动已安装" : "环境已就绪" })).toBeNull();
  expect(screen.getByText("用时 1 分 23 秒")).toBeTruthy();
  expect(screen.queryByRole("progressbar")).toBeNull();
  expect(screen.getByRole("button", { name: "关闭" })).toBeTruthy();
});

test.each(["checkEnvironment", "downloadChromeDriver"] as const)("%s errors retain the real failure reason and can be closed", operation => {
  const close = vi.fn();
  render(<EnvironmentProgressDialog progress={{ ...progress, operation, status: "error", stage: "error",
    updated_at: start + 90, message: "下载超时，请检查网络连接。" }} open onClose={close} />);
  expect(screen.getByRole("heading", { name: operation === "checkEnvironment" ? "环境检查未完成" : "驱动下载未完成" })).toBeTruthy();
  expect(screen.getByRole("status").textContent).toContain("下载超时，请检查网络连接。");
  expect(screen.getByText("下载超时，请检查网络连接。")).toBeTruthy();
  expect(screen.getByText("请根据下方原因处理后重试。")).toBeTruthy();
  expect(screen.queryByRole("progressbar")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "关闭" }));
  expect(close).toHaveBeenCalledTimes(1);
});
