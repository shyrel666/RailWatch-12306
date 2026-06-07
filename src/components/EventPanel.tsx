import { useState } from "react";
import { Button, Select, Tooltip } from "antd";
import { Eraser, FileDown, Pause } from "lucide-react";
import { railwatchApi } from "../lib/railwatchApi";
import { useRailWatchStore } from "../store/useRailWatchStore";
import type { CommandRunner } from "./componentTypes";

export function EventPanel({ runCommand }: { runCommand: CommandRunner }) {
  const logs = useRailWatchStore((state) => state.logs);
  const errorCount = useRailWatchStore((state) => state.errorCount);
  const filteredLogs = useRailWatchStore((state) => state.filteredLogs);
  const logPaused = useRailWatchStore((state) => state.logPaused);
  const setLogPaused = useRailWatchStore((state) => state.setLogPaused);
  const clearLogs = useRailWatchStore((state) => state.clearLogs);
  const runtime = useRailWatchStore((state) => state.runtime);
  const [filter, setFilter] = useState("全部");
  const visibleLogs = filteredLogs(filter);
  const exportLog = async () => {
    const defaultPath = runtime.data_dir ? `${runtime.data_dir}/railwatch-events.txt` : undefined;
    const path = await railwatchApi.showSaveDialog(defaultPath);
    if (path) {
      await runCommand("exportLog", { path }, "事件已导出");
    }
  };
  const clearBothLogs = async () => {
    clearLogs();
    await runCommand("clearLog");
  };
  return (
    <aside className="event-panel">
      <div className="event-head">
        <div>
          <h2>事件</h2>
          <span>
            {logs.length} 条事件 · {errorCount()} 个错误
          </span>
        </div>
        <Select
          value={filter}
          onChange={setFilter}
          options={["全部", "信息", "警告", "错误", "成功"].map((value) => ({ value, label: value }))}
          size="small"
          className="event-filter"
        />
      </div>
      <div className="event-actions">
        <Tooltip title={logPaused ? "恢复滚动" : "暂停滚动"}>
          <Button
            aria-label={logPaused ? "恢复滚动" : "暂停滚动"}
            icon={<Pause size={15} />}
            onClick={() => setLogPaused(!logPaused)}
            size="small"
            type={logPaused ? "primary" : "default"}
          />
        </Tooltip>
        <Tooltip title="清空事件">
          <Button aria-label="清空事件" icon={<Eraser size={15} />} onClick={() => void clearBothLogs()} size="small" />
        </Tooltip>
        <Tooltip title="导出事件">
          <Button aria-label="导出事件" icon={<FileDown size={15} />} onClick={() => void exportLog()} size="small" />
        </Tooltip>
      </div>
      <div className={logPaused ? "event-list paused" : "event-list"}>
        {visibleLogs.map((entry, index) => (
          <div className={`event-entry ${entry.level.toLowerCase()}`} key={`${entry.time}-${index}`}>
            <span>{entry.time}</span>
            <strong>{entry.level}</strong>
            <p>{entry.message}</p>
          </div>
        ))}
      </div>
    </aside>
  );
}
