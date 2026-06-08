import path from "node:path";
import { describe, expect, test } from "vitest";
import {
  consumeExportPathGrant,
  getCommandConfirmation,
  isExportPathAllowed,
  isRailWatchCommand,
  isTrustedRailWatchUrl,
  recordExportPathGrant,
} from "../ipcSecurity";

describe("ipcSecurity", () => {
  test("accepts only known RailWatch runtime commands", () => {
    expect(isRailWatchCommand("getRuntimeInfo")).toBe(true);
    expect(isRailWatchCommand("clearLocalData")).toBe(true);
    expect(isRailWatchCommand("shell")).toBe(false);
  });

  test("trusts only the configured renderer URL", () => {
    expect(isTrustedRailWatchUrl("http://127.0.0.1:5173/settings", "http://127.0.0.1:5173")).toBe(true);
    expect(isTrustedRailWatchUrl("http://localhost:5173/settings", "http://127.0.0.1:5173")).toBe(false);
    expect(isTrustedRailWatchUrl("file:///app/dist/index.html", "file:///app/dist/index.html")).toBe(true);
    expect(isTrustedRailWatchUrl("file:///app/dist/other.html", "file:///app/dist/index.html")).toBe(false);
  });

  test("requires main-process confirmation for destructive or automated commands", () => {
    expect(getCommandConfirmation("clearLocalData", {})).toMatchObject({ title: "清除本地数据" });
    expect(getCommandConfirmation("closeBrowser", {})).toMatchObject({ title: "关闭浏览器" });
    expect(getCommandConfirmation("startMonitor", { config: { auto_submit: true } })).toMatchObject({ title: "确认自动化" });
    expect(getCommandConfirmation("startMonitor", { config: { auto_alternate: true } })).toMatchObject({ title: "确认自动化" });
    expect(getCommandConfirmation("startMonitor", { config: { auto_submit: false, auto_alternate: false } })).toBeNull();
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
