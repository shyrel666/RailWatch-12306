import { describe, expect, test } from "vitest";
import { createRailWatchStore, defaultStatus } from "./railwatchStore";
import { getDateRangeStatus, todayIso } from "../lib/tripDate";

describe("bounded logs and task ownership", () => {
  test("100,000 events remain bounded through pause and resume", () => {
    const store = createRailWatchStore();
    for (let index = 0; index < 100_000; index++) {
      if (index === 50_000) store.getState().setLogPaused(true);
      store.getState().applyLog({ time:"12:00:00", level:"INFO", message:`event-${index}` });
    }
    expect(store.getState().logs).toHaveLength(1000);
    expect(store.getState().pausedLogs).toHaveLength(1000);
    store.getState().setLogPaused(false);
    expect(store.getState().logs).toHaveLength(1000);
    expect(store.getState().droppedLogs).toBe(99_000);
    expect(store.getState().logs[0].message).toBe("event-99000");
    expect(new Set(store.getState().logs.map(entry => entry.id)).size).toBe(1000);
    store.getState().clearLogs();
    expect(store.getState().droppedLogs).toBe(0);
  });

  test("old ticks, notifications, and final states cannot replace a new task", () => {
    const store = createRailWatchStore();
    store.getState().applyState({ ...defaultStatus, task:{run_id:"old", status:"querying"} });
    store.getState().applyState({ ...defaultStatus, task:{run_id:"new", status:"querying"} });
    store.getState().applyMonitorTick({ run_id:"old", loop:99, date:"2026-09-06", rows:[{train:"OLD",raw:"OLD"}] });
    store.getState().applyNotify({ run_id:"old", title:"old", message:"old" });
    store.getState().applyState({ ...defaultStatus, task:{run_id:"old", status:"stopped"} });
    expect(store.getState().status.task?.run_id).toBe("new");
    expect(store.getState().monitorLoops).toBe(0);
    expect(store.getState().results).toEqual([]);
    expect(store.getState().notifications).toEqual([]);
  });

  test("date validation uses Beijing midnight and filters partial ranges", () => {
    const now = new Date("2026-09-05T16:00:00Z");
    expect(todayIso(now)).toBe("2026-09-06");
    expect(getDateRangeStatus("2026-09-06", "±1天", now)).toEqual({ valid:["2026-09-06","2026-09-07"], skipped:["2026-09-05"], invalid:false });
    expect(getDateRangeStatus("2026-02-30", "单日", now).invalid).toBe(true);
    expect(getDateRangeStatus("2026-09-20", "±1天", now).valid).toEqual(["2026-09-19","2026-09-20"]);
  });

  test("a delayed start response cannot roll the same task backwards", () => {
    const store = createRailWatchStore();
    store.getState().applyState({...defaultStatus, task:{run_id:"one",status:"querying",sequence:3}});
    store.getState().applyState({...defaultStatus, task:{run_id:"one",status:"preparing",sequence:1}});
    expect(store.getState().status.task?.status).toBe("querying");
  });
});
