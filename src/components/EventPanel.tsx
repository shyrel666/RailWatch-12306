import { useState } from "react";
import { Button, Select, Tooltip } from "antd";
import { Eraser, FileDown, Pause, X } from "lucide-react";
import { railwatchApi } from "../lib/railwatchApi";
import { useRailWatchStore } from "../store/useRailWatchStore";
import type { CommandRunner } from "./componentTypes";

export function EventPanel({ onClose, runCommand }: { onClose: () => void; runCommand: CommandRunner }) {
  const logs = useRailWatchStore((state) => state.logs);
  const errorCount = useRailWatchStore((state) => state.errorCount);
  const filteredLogs = useRailWatchStore((state) => state.filteredLogs);
  const logPaused = useRailWatchStore((state) => state.logPaused);
  const setLogPaused = useRailWatchStore((state) => state.setLogPaused);
  const clearLogs = useRailWatchStore((state) => state.clearLogs);
  const runtime = useRailWatchStore((state) => state.runtime);
  const [filter, setFilter] = useState("全部");
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
  const visibleLogs = [...filteredLogs(filter)].sort(
    (a, b) => Number(b.level === "ERROR") - Number(a.level === "ERROR"),
  );

  return (
    <aside className="event-panel" aria-label="事件面板">
      <div className="event-head">
        <div>
          <h2>事件</h2>
          <span>
            <span>当前显示 {visibleLogs.length} 条</span>
            <span> · {errorCount()} 个错误</span>
          </span>
          {logPaused ? <span className="event-paused">事件流已暂停</span> : null}
        </div>
        <Tooltip title="隐藏事件面板">
          <Button aria-label="隐藏事件面板" icon={<X size={15} />} onClick={onClose} size="small" />
        </Tooltip>
      </div>
      <div className="event-toolbar">
        <Select
          value={filter}
          onChange={setFilter}
          options={["全部", "信息", "警告", "错误", "成功"].map((value) => ({ value, label: value }))}
          size="small"
          className="event-filter"
        />
        <Tooltip title={logPaused ? "恢复滚动" : "暂停滚动"}>
          <Button
            aria-label={logPaused ? "恢复滚动" : "暂停滚动"}
            aria-pressed={logPaused}
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
      <div className={logPaused ? "event-list paused" : "event-list"} role="feed" aria-label="事件流">
        {visibleLogs.map((entry, index) => (
          <article className={`event-entry ${entry.level.toLowerCase()}`} key={`${entry.time}-${index}`}>
            <span>{entry.time}</span>
            <strong>{entry.level}</strong>
            <p>{entry.message}</p>
          </article>
        ))}
      </div>
    </aside>
  );
}
