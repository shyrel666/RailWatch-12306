import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { railwatchStore } from "../store/railwatchStore";
import { railwatchApi } from "./railwatchApi";
import { exportEventLog } from "./exportEventLog";

beforeEach(() => railwatchStore.getState().clearLogs());
afterEach(() => vi.restoreAllMocks());

test("exports raw records, stderr and pause buffer received while the dialog is open", async () => {
  railwatchStore.setState({ logPaused: false });
  railwatchStore.getState().applyLog({ time: "09:00:00", level: "INFO", message: "Python 3.10.8" });
  const showDialog = vi.spyOn(railwatchApi, "showSaveDialog").mockImplementation(async () => {
    railwatchStore.getState().applyLog({ time: "09:00:01", level: "WARN", message: "stderr diagnostic" });
    railwatchStore.getState().setLogPaused(true);
    railwatchStore.getState().applyLog({ time: "09:00:02", level: "ERROR", message: "暂停期间的错误" });
    return "C:/events.txt";
  });
  const runCommand = vi.fn(async () => undefined);
  await exportEventLog("C:/default.txt", runCommand);
  expect(showDialog).toHaveBeenCalledWith("C:/default.txt");
  expect(runCommand).toHaveBeenCalledWith("exportLog", {
    path: "C:/events.txt",
    entries: [
      { time: "09:00:00", level: "INFO", message: "Python 3.10.8" },
      { time: "09:00:01", level: "WARN", message: "stderr diagnostic" },
      { time: "09:00:02", level: "ERROR", message: "暂停期间的错误" },
    ],
  }, "事件已导出");
});

test("cancelled export does not invoke the backend", async () => {
  vi.spyOn(railwatchApi, "showSaveDialog").mockResolvedValue(null);
  const runCommand = vi.fn();
  await exportEventLog(undefined, runCommand);
  expect(runCommand).not.toHaveBeenCalled();
});

test("an empty renderer snapshot is exported explicitly", async () => {
  vi.spyOn(railwatchApi, "showSaveDialog").mockResolvedValue("C:/events.txt");
  const runCommand = vi.fn();
  await exportEventLog(undefined, runCommand);
  expect(runCommand).toHaveBeenCalledWith("exportLog", { path: "C:/events.txt", entries: [] }, "事件已导出");
});
