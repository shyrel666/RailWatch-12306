import type { CommandRunner } from "../components/componentTypes";
import { railwatchStore } from "../store/railwatchStore";

export async function exportEventLog(defaultPath: string | undefined, runCommand: CommandRunner,
  choosePath: (defaultPath?: string) => Promise<string | null>) {
  const path = await choosePath(defaultPath);
  if (!path) return;

  const { logs, pausedLogs } = railwatchStore.getState();
  // Export all retained raw records, including events buffered during pause.
  // Take the snapshot after the dialog closes so newly received events survive.
  const entries = [...logs, ...pausedLogs].map(({ time, level, message }) => ({ time, level, message }));
  await runCommand("exportLog", { path, entries }, "事件已导出");
}
