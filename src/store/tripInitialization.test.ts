import { expect, test } from "vitest";
import { createRailWatchStore, defaultConfig } from "./railwatchStore";

const noDraft = { status: "missing" as const, draft: null, warning: null };

test("a delayed initial load preserves typed fields and loads untouched saved fields", () => {
  const store = createRailWatchStore();
  store.getState().setConfig({ from_station_cn: "北京南", train_code: "G19", date_range: "单日" });
  store.getState().setConfig({ train_code: "" });
  const revision = store.getState().editRevision;
  const saved = { ...defaultConfig, from_station_cn: "北京", to_station_cn: "上海虹桥", train_code: "G23", interval: 9 };
  store.getState().initializeTrip(saved, 123, noDraft);

  expect(store.getState().config).toMatchObject({ from_station_cn: "北京南", to_station_cn: "上海虹桥", train_code: "", interval: 9 });
  expect(store.getState().savedConfig).toEqual(saved);
  expect(store.getState().editRevision).toBe(revision);
  expect(store.getState().draftSaveState).toBe("editing");
  expect(store.getState().tripInitialized).toBe(true);
});

test("explicit restore after initialization replaces edits with the saved trip", () => {
  const store = createRailWatchStore();
  const saved = { ...defaultConfig, train_code: "G23" };
  store.getState().setConfig({ train_code: "G19" });
  store.getState().initializeTrip(saved, 123, noDraft);
  store.getState().initializeTrip(saved, 123, noDraft);

  expect(store.getState().config).toEqual(saved);
  expect(store.getState().editRevision).toBe(0);
  expect(store.getState().draftSaveState).toBe("idle");
});
