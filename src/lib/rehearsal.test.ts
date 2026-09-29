import { describe, expect, test } from "vitest";
import { createRailWatchStore, defaultConfig, defaultStatus, tripFingerprint } from "../store/railwatchStore";
import { needsRehearsal, rehearsalDisabled, rehearsalExpired, type RehearsalReport } from "./rehearsal";
import { dashboardAction } from "./dashboardState";

export const rehearsalReport: RehearsalReport = { schema_version: 1, rehearsal_id: "rehearsal-1", trigger: "manual",
  started_at: 1, finished_at: 2, verdict: "ready", trip: { from_station: "北京", to_station: "上海", date: "2026-10-12", sale_at: "" },
  checks: [{ id: "login", title: "登录会话", critical: true, status: "pass", summary: "登录会话有效", duration_ms: 30 }], measurements: {}, prediction: [] };

describe("rehearsal state", () => {
  test("captures the requested config and rejects foreign or late events", () => {
    const store = createRailWatchStore();
    const state = store.getState();
    state.prepareRehearsal(defaultConfig);
    state.applyRehearsalStarted({ rehearsal_id: "rehearsal-1", trigger: "manual", checks: rehearsalReport.checks });
    state.setConfig({ train_code: "G9" });
    state.applyRehearsalStep({ rehearsal_id: "foreign", check: { ...rehearsalReport.checks[0], status: "fail" } });
    expect(store.getState().rehearsal.checks[0].status).toBe("pass");
    state.applyRehearsalFinished({ report: rehearsalReport });
    expect(rehearsalExpired(store.getState().rehearsal.fingerprint, tripFingerprint(store.getState().config))).toBe(true);
    state.prepareRehearsal(defaultConfig);
    state.applyRehearsalStarted({ rehearsal_id: "new", trigger: "manual", checks: [] });
    state.applyRehearsalFinished({ report: rehearsalReport });
    expect(store.getState().rehearsal.activeId).toBe("new");
    state.resetRehearsalProgress();
    expect(store.getState().rehearsal.activeId).toBeNull();
  });
  test("history has no private config fingerprint and needs a fresh rehearsal", () => {
    const store = createRailWatchStore();
    store.getState().loadRehearsalHistory(rehearsalReport);
    expect(rehearsalExpired(store.getState().rehearsal.fingerprint, tripFingerprint(defaultConfig))).toBe(true);
    expect(needsRehearsal({ ...defaultConfig, auto_submit: true }, rehearsalReport, false)).toBe(false);
    expect(needsRehearsal({ ...defaultConfig, auto_submit: true }, rehearsalReport, true)).toBe(true);
  });
  test("disabled reasons and dashboard priority", () => {
    const now = Date.now();
    expect(rehearsalDisabled(defaultConfig, now, true, true, true)).toContain("监控");
    expect(rehearsalDisabled(defaultConfig, now, false, true, false)).toContain("订单");
    expect(rehearsalDisabled(defaultConfig, now, false, false, false, now / 1000 - 30)).toContain("冷却");
    expect(rehearsalDisabled({ ...defaultConfig, timer_enabled: true, sale_at: new Date(now + 1000).toISOString() }, now, false, false, false)).toContain("五分钟");
    const ready = { ...defaultStatus, environment_ready: true, login_ready: true, query_ready: true };
    expect(dashboardAction(ready, null, true, true).section).toBe("monitor-rehearsal");
    expect(dashboardAction({ ...ready, monitoring: true }, null, true, true).section).toBe("monitor-controls");
    expect(dashboardAction(ready, null, false, true).section).toBe("trip-basics");
  });
});
