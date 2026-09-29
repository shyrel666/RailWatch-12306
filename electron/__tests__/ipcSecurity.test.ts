import path from "node:path";
import { describe, expect, test } from "vitest";
import {
  consumeExportPathGrant,
  getCommandConfirmation,
  isAllowedExternalUrl,
  isExportPathAllowed,
  isRailWatchCommand,
  isTrustedRailWatchUrl,
  recordExportPathGrant,
} from "../ipcSecurity";

describe("ipcSecurity", () => {
  test("accepts only known RailWatch runtime commands", () => {
    expect(isRailWatchCommand("getRuntimeInfo")).toBe(true);
    expect(isRailWatchCommand("checkLogin")).toBe(true);
    expect(isRailWatchCommand("stationSaleTimes")).toBe(true);
    expect(isRailWatchCommand("clearLocalData")).toBe(true);
    expect(isRailWatchCommand("shell")).toBe(false);
  });

  test("trusts only the configured renderer URL", () => {
    expect(isTrustedRailWatchUrl("http://127.0.0.1:5173/settings", "http://127.0.0.1:5173")).toBe(true);
    expect(isTrustedRailWatchUrl("http://localhost:5173/settings", "http://127.0.0.1:5173")).toBe(false);
    expect(isTrustedRailWatchUrl("file:///app/dist/index.html", "file:///app/dist/index.html")).toBe(true);
    expect(isTrustedRailWatchUrl("file:///app/dist/other.html", "file:///app/dist/index.html")).toBe(false);
  });

  test("opens only https GitHub links externally", () => {
    expect(isAllowedExternalUrl("https://github.com/shyrel666/RailWatch-12306")).toBe(true);
    expect(isAllowedExternalUrl("https://github.com/shyrel666/RailWatch-12306/releases")).toBe(true);
    expect(isAllowedExternalUrl("http://github.com/shyrel666/RailWatch-12306")).toBe(false);
    expect(isAllowedExternalUrl("https://gist.github.com/example")).toBe(false);
    expect(isAllowedExternalUrl("https://github.com.evil.example/")).toBe(false);
    expect(isAllowedExternalUrl("file:///C:/Windows/System32/calc.exe")).toBe(false);
    expect(isAllowedExternalUrl("javascript:alert(1)")).toBe(false);
    expect(isAllowedExternalUrl(42)).toBe(false);
  });

  test("allows only the specific official sale-time page", () => {
    expect(isAllowedExternalUrl("https://kyfw.12306.cn/index/view/infos/sale_time.html")).toBe(true);
    expect(isAllowedExternalUrl("https://kyfw.12306.cn/otn/login/init")).toBe(false);
    expect(isAllowedExternalUrl("https://kyfw.12306.cn/index/view/infos/sale_time.html?url=evil")).toBe(false);
    expect(isAllowedExternalUrl("https://kyfw.12306.cn.evil.example/index/view/infos/sale_time.html")).toBe(false);
  });

  test("requires main-process confirmation for destructive or automated commands", () => {
    expect(getCommandConfirmation("clearLocalData", {})).toMatchObject({ title: "清除本地数据" });
    expect(getCommandConfirmation("closeBrowser", {})).toMatchObject({ title: "关闭浏览器" });
    expect(getCommandConfirmation("startMonitor", { config: { auto_submit: true } })).toMatchObject({ title: "核对本次监控" });
    expect(getCommandConfirmation("startMonitor", { config: { auto_alternate: true } })).toMatchObject({ title: "核对本次监控" });
    expect(getCommandConfirmation("startMonitor", { confirmed: true, config: { auto_submit: false, auto_alternate: false } })).toMatchObject({ title: "核对本次监控" });
  });

  test("allows export paths only after the save dialog granted them", () => {
    const grants = new Set<string>();
    const chosenPath = path.join("C:", "Users", "test", "events.txt");
    const otherPath = path.join("C:", "Users", "test", "other.txt");

    expect(isExportPathAllowed("exportLog", { path: chosenPath }, grants)).toBe(false);
    recordExportPathGrant(chosenPath, grants);
    expect(isExportPathAllowed("exportLog", { path: chosenPath }, grants)).toBe(true);
    expect(isExportPathAllowed("exportLog", { path: otherPath }, grants)).toBe(false);

    consumeExportPathGrant("exportLog", { path: chosenPath }, grants);
    expect(isExportPathAllowed("exportLog", { path: chosenPath }, grants)).toBe(false);
    expect(isExportPathAllowed("exportLog", {}, grants)).toBe(true);
  });
});

test("rehearsal commands are restricted and explain the offline boundary", () => {
  expect(isRailWatchCommand("clearRehearsalHistory")).toBe(true);
  expect(getCommandConfirmation("clearRehearsalHistory", {})?.message).toContain("订单和实战复盘记录会保留");
  for (const command of ["rehearse", "cancelRehearsal", "rehearsalHistory", "runReviews", "runReview"]) expect(isRailWatchCommand(command)).toBe(true);
  const prompt = getCommandConfirmation("rehearse", { config: { sale_at: new Date(Date.now() + 600_000).toISOString() } });
  expect(prompt?.message).toContain("不会创建订单");
  expect(prompt?.message).toContain("不足 15 分钟");
  expect(getCommandConfirmation("cancelRehearsal", {})).toBeNull();
});
