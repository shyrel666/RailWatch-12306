import type { CommandRunner } from "../components/componentTypes";
import { railwatchStore } from "../store/railwatchStore";
import { railwatchApi } from "./railwatchApi";

export async function exportEventLog(defaultPath: string | undefined, runCommand: CommandRunner) {
  const path = await railwatchApi.showSaveDialog(defaultPath);
  if (!path) return;

  const { logs, pausedLogs } = railwatchStore.getState();
  // Export all retained raw records, including events buffered during pause.
  // Take the snapshot after the dialog closes so newly received events survive.
  const entries = [...logs, ...pausedLogs].map(({ time, level, message }) => ({ time, level, message }));
  await runCommand("exportLog", { path, entries }, "事件已导出");
}
