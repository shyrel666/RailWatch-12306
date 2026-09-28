import { describe, expect, test } from "vitest";
import { createRailWatchStore, defaultStatus } from "./railwatchStore";
import { queryConfig, querySnapshot, queryTime } from "../test/queryFixtures";
import type { QuerySnapshot } from "../types";
import { queryFreshness } from "../lib/queryResults";

function monitorStore() {
  const store = createRailWatchStore();
  store.getState().setConfig(queryConfig);
  store.getState().applyState({ ...defaultStatus, monitoring: true, task: { run_id: "run", status: "querying" }, current_config: queryConfig });
  return store;
}
function tick(store: ReturnType<typeof createRailWatchStore>, snapshot: QuerySnapshot) {
  store.getState().applyMonitorTick({ run_id: snapshot.run_id ?? undefined, loop: snapshot.sequence, date: snapshot.conditions.date,
    rows: snapshot.rows, snapshot });
}

describe("structured query ownership and per-date retention", () => {
  test("two dates retain the same train independently; empty success clears only its date", () => {
    const store = monitorStore();
    const first = querySnapshot();
    const second = querySnapshot({ query_id: "q2", sequence: 2, conditions: { ...first.conditions, date: "2026-09-23" },
      rows: first.rows.map(r => ({ ...r, date: "2026-09-23" })) });
    tick(store, first); tick(store, second);
    expect(store.getState().results.map(r => r.date)).toEqual(["2026-09-22", "2026-09-23"]);
    tick(store, { ...first, query_id: "q3", sequence: 3, rows: [] });
    expect(store.getState().results.map(r => r.date)).toEqual(["2026-09-23"]);
    expect(Object.values(store.getState().queryViews)).toHaveLength(2);
  });

  test("failure retains the last successful rows/time and rejects a late earlier success", () => {
    const store = monitorStore();
    tick(store, querySnapshot());
    tick(store, querySnapshot({ query_id: "q3", sequence: 3, status: "error", error: "HTTP 429", fetched_at: null, rows: [] }));
    tick(store, querySnapshot({ query_id: "q2", sequence: 2, fetched_at: queryTime + 10, rows: [] }));
    const view = Object.values(store.getState().queryViews)[0];
    expect(view.latest.error).toBe("HTTP 429");
    expect(view.success?.fetched_at).toBe(queryTime);
    expect(store.getState().results).toHaveLength(1);
  });

  test("old runs and wrong route/date/seat snapshots cannot contaminate current results", () => {
    const store = monitorStore();
    const snap = querySnapshot();
    tick(store, { ...snap, run_id: "retired" });
    for (const patch of [{ from_station: "广州" }, { date: "2026-10-01" }, { seat_types: ["商务座"] }])
      tick(store, { ...snap, conditions: { ...snap.conditions, ...patch } });
    expect(store.getState().results).toEqual([]);
    expect(store.getState().queryViews).toEqual({});
  });

  test("editing a running task keeps its frozen results; a new task starts clean", () => {
    const store = monitorStore();
    store.getState().setConfig({ from_station_cn: "广州" });
    tick(store, querySnapshot());
    expect(store.getState().results).toHaveLength(1);
    expect(store.getState().queryConfig?.from_station_cn).toBe("北京");
    store.getState().applyState({ ...store.getState().status, task: { run_id: "next", status: "querying" }, current_config: store.getState().config });
    expect(store.getState().results).toEqual([]);
    tick(store, querySnapshot());
    expect(store.getState().results).toEqual([]);
  });

  test("manual requests are isolated, including same-route repeated requests and late timeout responses", () => {
    const store = createRailWatchStore();
    store.getState().setConfig(queryConfig);
    const snapshot = querySnapshot({ run_id: null });
    store.getState().beginManualQuery("old", queryConfig);
    store.getState().beginManualQuery("new", queryConfig);
    store.getState().applyResults({ request_id: "old", snapshots: [snapshot], rows: snapshot.rows });
    expect(store.getState().results).toEqual([]);
    store.getState().applyResults({ request_id: "new", snapshots: [snapshot], rows: snapshot.rows });
    store.getState().endManualQuery("new");
    store.getState().beginManualQuery("retry", queryConfig);
    store.getState().applyResults({ request_id: "retry", snapshots: [{ ...snapshot, status: "error", error: "断网", rows: [], fetched_at: null }], rows: [] });
    expect(store.getState().results).toHaveLength(1);
    store.getState().endManualQuery("retry", "超时");
    store.getState().applyResults({ request_id: "retry", snapshots: [{ ...snapshot, sequence: 99, rows: [] }], rows: [] });
    expect(store.getState().results).toHaveLength(1);
    expect(store.getState().manualQueryError).toBe("超时");
  });

  test("editing inactive conditions invalidates in-flight manual responses", () => {
    const store = createRailWatchStore();
    store.getState().setConfig(queryConfig);
    store.getState().beginManualQuery("one", queryConfig);
    store.getState().setConfig({ to_station_cn: "南京" });
    store.getState().applyResults({ request_id: "one", snapshots: [querySnapshot({ run_id: null })], rows: [] });
    expect(store.getState().manualQueryId).toBeNull();
    expect(store.getState().queryViews).toEqual({});
    expect(store.getState().manualQueryError).toContain("本次查询结果已作废");
  });

  test("stopped tasks reject late results and query-start events", () => {
    const store = monitorStore();
    const snapshot = querySnapshot();
    tick(store, snapshot);
    store.getState().applyQueryStarted({ ...snapshot, started_at: queryTime });
    expect(store.getState().activeQuery).toBeNull();
    store.getState().applyQueryStarted({ ...snapshot, query_id: "q2", sequence: 2, started_at: queryTime });
    expect(store.getState().activeQuery?.query_id).toBe("q2");
    store.getState().applyState({ ...store.getState().status, monitoring: false });
    tick(store, { ...snapshot, sequence: 3, rows: [] });
    store.getState().applyQueryStarted({ ...snapshot, sequence: 4, started_at: queryTime });
    expect(store.getState().activeQuery).toBeNull();
    expect(store.getState().results).toHaveLength(1);
  });

  test("legacy events do not erase structured results", () => {
    const store = monitorStore();
    tick(store, querySnapshot());
    store.getState().applyMonitorTick({ run_id: "run", loop: 99, date: queryConfig.date, rows: [] });
    store.getState().applyResults({ rows: [] });
    expect(store.getState().results).toHaveLength(1);
  });
});

test("status reload restores structured human action and rejects inconsistent replay counters", () => {
  const store = monitorStore();
  const action = { title: "核验", message: "请在官方页面处理" };
  store.getState().applyState({ ...store.getState().status, human_action: action });
  expect(store.getState().lastHumanAction).toEqual(action);
  store.getState().clearHumanAction();
  store.getState().applyState({ ...store.getState().status, human_action: action });
  expect(store.getState().lastHumanAction).toBeNull();
  const snap = querySnapshot({ sequence: 4 });
  tick(store, snap);
  store.getState().applyMonitorTick({ run_id: snap.run_id!, loop: 9, date: snap.conditions.date, rows: snap.rows, snapshot: snap });
  expect(store.getState().monitorLoops).toBe(4);
  tick(store, { ...snap, sequence: 9, query_id: "q9" });
  expect(store.getState().monitorLoops).toBe(9);
});

test("freshness accounts for query timeout, multi-date cycles, backoff and stopping", () => {
  const snap = querySnapshot();
  const view = { owner: "run", latest: snap, success: snap };
  const active = { ...defaultStatus, monitoring: true, task: { status: "backoff", next_query_at: queryTime + 10 } };
  expect(queryFreshness(view, active, queryConfig, queryTime + 2)).toContain("等待下一轮");
  expect(queryFreshness(view, active, queryConfig, queryTime + 100)).toContain("已过期");
  expect(queryFreshness(view, { ...active, monitoring: false }, queryConfig, queryTime + 2)).toContain("当前未监控");
  expect(queryFreshness(view, { ...active, task: { status: "stopping" } }, queryConfig, queryTime + 2)).toContain("已暂停");
  expect(queryFreshness({ ...view, latest: { ...snap, status: "error", error: "限频" } }, active, queryConfig, queryTime)).toContain("本轮查询失败");
});
