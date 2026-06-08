import { describe, expect, test } from "vitest";
import { createRailWatchStore } from "./railwatchStore";

describe("railwatchStore", () => {
  test("applies runtime info and bridge state without changing feature names", () => {
    const store = createRailWatchStore();

    store.getState().applyRuntimeInfo({
      app_display_name: "RailWatch 12306",
      app_version: "0.1.0",
      app_slug: "railwatch-12306",
      pages: ["仪表盘", "行程设置", "购票监控", "系统设置"],
      data_dir: "C:/Users/test/AppData/Local/railwatch-12306",
      data_dir_writable: true,
      data_dir_free_bytes: 64_000_000_000,
      chromedriver_path: "C:/driver/chromedriver.exe",
      chrome_version: "Chrome 120",
      core_available: true,
      core_import_error: "",
      selenium_available: true,
      chromedriver_manager_available: true,
      network_ok: true,
      network_label: "正常",
      railway_ok: true,
      railway_label: "正常",
      proxy_configured: false,
      proxy_label: "未配置",
      proxy_value: "",
      state: {
        phase: "query_ready",
        environment_ready: true,
        login_ready: true,
        query_ready: true,
        monitoring: false,
        auto_submit_enabled: false,
        auto_alternate_enabled: false,
        risk_level: "notice",
        status_message: "已解析 2 行查询结果",
        error_message: "",
        current_config: {},
        hits: [],
        summary: "已解析 2 行查询结果",
      },
    });

    const state = store.getState();
    expect(state.runtime.app_display_name).toBe("RailWatch 12306");
    expect(state.runtime.pages).toEqual(["仪表盘", "行程设置", "购票监控", "系统设置"]);
    expect(state.status.phase).toBe("query_ready");
    expect(state.status.query_ready).toBe(true);
  });

  test("keeps log counts and filters aligned with the event panel", () => {
    const store = createRailWatchStore();

    store.getState().applyLog({ time: "09:00:00", level: "INFO", message: "系统就绪" });
    store.getState().applyLog({ time: "09:01:00", level: "ERROR", message: "登录已过期" });

    expect(store.getState().logs).toHaveLength(2);
    expect(store.getState().errorCount()).toBe(1);
    expect(store.getState().filteredLogs("错误")).toEqual([
      { time: "09:01:00", level: "ERROR", message: "登录已过期" },
    ]);
  });

  test("buffers logs while paused and flushes them on resume", () => {
    const store = createRailWatchStore();

    store.getState().applyLog({ time: "09:00:00", level: "INFO", message: "before pause" });
    store.getState().setLogPaused(true);
    store.getState().applyLog({ time: "09:00:01", level: "INFO", message: "while paused" });

    expect(store.getState().logs.map((entry) => entry.message)).toEqual(["before pause"]);

    store.getState().setLogPaused(false);

    expect(store.getState().logs.map((entry) => entry.message)).toEqual(["before pause", "while paused"]);
  });

  test("records query results and ticket hits from runtime events", () => {
    const store = createRailWatchStore();

    store.getState().applyResults({
      rows: [
        { train: "G101", raw: "G101 北京 上海 二等座 有" },
        { train: "G103", raw: "G103 北京 上海 二等座 候补" },
      ],
    });
    store.getState().applyNotify({
      title: "发现目标车票",
      message: "命中：G101\n请立即确认订单",
      hit: {
        train_code: "G101",
        seat_type: "目标席别",
        status: "available",
        source: "regular",
        detail: "命中：G101\n请立即确认订单",
        label: "G101 目标席别 有票: available",
      },
    });

    const state = store.getState();
    expect(state.results.map((row) => row.train)).toEqual(["G101", "G103"]);
    expect(state.hits[0].train_code).toBe("G101");
    expect(state.notifications[0].title).toBe("发现目标车票");
  });

  test("does not yank the active page when a hit notification arrives", () => {
    const store = createRailWatchStore();
    store.getState().setActivePage("行程设置");

    store.getState().applyNotify({
      title: "发现目标车票",
      message: "命中：G101",
      hit: {
        train_code: "G101",
        seat_type: "二等座",
        status: "有",
        source: "regular",
        detail: "命中：G101",
        label: "G101 二等座 有票: 有",
      },
    });

    expect(store.getState().activePage).toBe("行程设置");
    expect(store.getState().notifications).toHaveLength(1);
  });

  test("applies live monitor ticks to results and loop count", () => {
    const store = createRailWatchStore();

    store.getState().applyMonitorTick({
      loop: 7,
      date: "2026-06-10",
      rows: [{ train: "G55", raw: "G55 北京 上海 二等座 有" }],
    });

    expect(store.getState().monitorLoops).toBe(7);
    expect(store.getState().results.map((row) => row.train)).toEqual(["G55"]);
    expect(store.getState().activePage).toBe("仪表盘");
  });

  test("applies runtime label patches from backend events", () => {
    const store = createRailWatchStore();

    store.getState().applyRuntimeLabels({
      chromedriver_path: "D:/RailWatch/chromedriver.exe",
      chrome_version: "Chrome 148",
    });

    expect(store.getState().runtime.chromedriver_path).toBe("D:/RailWatch/chromedriver.exe");
    expect(store.getState().runtime.chrome_version).toBe("Chrome 148");
  });

  test("clears stale hits when backend state reports no hits", () => {
    const store = createRailWatchStore();

    store.getState().applyNotify({
      title: "发现目标车票",
      message: "命中：G101",
      hit: {
        train_code: "G101",
        seat_type: "二等座",
        status: "available",
        source: "regular",
        detail: "命中：G101",
        label: "G101 二等座 有票: available",
      },
    });

    expect(store.getState().hits).toHaveLength(1);

    store.getState().applyState({
      ...store.getState().status,
      hits: [],
    });

    expect(store.getState().hits).toEqual([]);
  });

  test("records the latest human-action handoff", () => {
    const store = createRailWatchStore();

    expect(store.getState().lastHumanAction).toBeNull();

    store.getState().applyHumanAction({
      title: "需要人工操作",
      message: "候补需要人工核验，请在浏览器中完成。",
      train_code: "G101",
    });

    expect(store.getState().lastHumanAction).toEqual({
      title: "需要人工操作",
      message: "候补需要人工核验，请在浏览器中完成。",
      train_code: "G101",
    });
  });

  test("syncs ticket hits from runtime info state", () => {
    const store = createRailWatchStore();
    const backendHit = {
      train_code: "G201",
      seat_type: "一等座",
      status: "available",
      source: "regular" as const,
      detail: "命中：G201",
      label: "G201 一等座 有票: available",
    };

    store.getState().applyRuntimeInfo({
      ...store.getState().runtime,
      state: {
        ...store.getState().status,
        hits: [backendHit],
      },
    });

    expect(store.getState().status.hits).toEqual([backendHit]);
    expect(store.getState().hits).toEqual([backendHit]);
  });
});
