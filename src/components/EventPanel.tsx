import { useMemo, useState } from "react";
import { Tooltip } from "antd";
import { Eraser, Pause, Play, FileDown } from "lucide-react";
import { countEventsByFilter, presentEventLogs } from "../lib/formatEventLog";
import { useRailWatchStore } from "../store/useRailWatchStore";
import type { CommandRunner } from "./componentTypes";

import { VirtualEventList } from "./VirtualEventList";

const filterLabels = ["全部", "信息", "警告", "错误"] as const;

export function EventPanel({
  onClose: _onClose,
  onExport,
  runCommand,
}: {
  onClose: () => void;
  onExport?: () => void;
  runCommand: CommandRunner;
}) {
  const logs = useRailWatchStore((state) => state.logs);
  const logPaused = useRailWatchStore((state) => state.logPaused);
  const setLogPaused = useRailWatchStore((state) => state.setLogPaused);
  const pausedCount = useRailWatchStore((state) => state.pausedLogs.length);
  const [filter, setFilter] = useState<(typeof filterLabels)[number]>("全部");
  const [clearing, setClearing] = useState(false);
  const clearBothLogs = async () => {
    setClearing(true);
    try {
      // The logsCleared event is the authoritative boundary. Clearing on the
      // response would also delete newer logs received after that event.
      await runCommand("clearLog");
    } finally {
      setClearing(false);
    }
  };
  const droppedLogs = useRailWatchStore((state) => state.droppedLogs);
  const visibleLogs = useMemo(
    () => presentEventLogs(logs, filter),
    [logs, filter],
  );
  const counts = useMemo(
    () =>
      Object.fromEntries(
        filterLabels.map((label) => [label, countEventsByFilter(logs, label)]),
      ),
    [logs],
  );
  const listClassName = [
    "event-list",
    logPaused ? "paused" : "",
    visibleLogs.length > 0 ? "has-events" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <aside className="event-panel" aria-label="事件面板">
      <div className="event-head">
        <span className="event-caption">运行记录</span>
        <div className="event-head-actions">
          {onExport ? (
            <button
              className="event-clear-btn"
              aria-label="导出日志"
              onClick={onExport}
              type="button"
            >
              <FileDown size={14} />
              导出
            </button>
          ) : null}
          <Tooltip title={logPaused ? "恢复事件流" : "暂停事件流"}>
            <button
              aria-label={logPaused ? "恢复事件流" : "暂停事件流"}
              aria-pressed={logPaused}
              className={
                logPaused ? "event-clear-btn active" : "event-clear-btn"
              }
              onClick={() => setLogPaused(!logPaused)}
              type="button"
            >
              {logPaused ? <Play size={14} /> : <Pause size={14} />}
              <span>
                {logPaused
                  ? `恢复${pausedCount ? `(${pausedCount})` : ""}`
                  : "暂停"}
              </span>
            </button>
          </Tooltip>
          <Tooltip title="清空事件">
            <button
              aria-label="清空事件"
              disabled={clearing}
              className="event-clear-btn"
              onClick={() => void clearBothLogs()}
              type="button"
            >
              <Eraser size={14} />
              <span>清空</span>
            </button>
          </Tooltip>
        </div>
      </div>
      <div className="event-tabs" role="tablist" aria-label="事件级别">
        {filterLabels.map((label) => (
          <button
            aria-selected={filter === label}
            className={filter === label ? "event-tab active" : "event-tab"}
            key={label}
            onClick={() => setFilter(label)}
            role="tab"
            type="button"
          >
            {label}
            <span>{counts[label]}</span>
          </button>
        ))}
      </div>
      {droppedLogs > 0 ? (
        <small role="status">
          仅保留最近 1,000 条日志，已丢弃 {droppedLogs} 条。
        </small>
      ) : null}
      <VirtualEventList entries={visibleLogs} className={listClassName} />
    </aside>
  );
}
