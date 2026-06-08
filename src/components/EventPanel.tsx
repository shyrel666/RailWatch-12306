import { useState } from "react";
import { Tooltip } from "antd";
import { Eraser } from "lucide-react";
import { countEventsByFilter, presentEventLogs } from "../lib/formatEventLog";
import { useRailWatchStore } from "../store/useRailWatchStore";
import type { CommandRunner } from "./componentTypes";

const filterLabels = ["全部", "信息", "警告", "错误"] as const;

export function EventPanel({ onClose: _onClose, runCommand }: { onClose: () => void; runCommand: CommandRunner }) {
  const logs = useRailWatchStore((state) => state.logs);
  const logPaused = useRailWatchStore((state) => state.logPaused);
  const clearLogs = useRailWatchStore((state) => state.clearLogs);
  const [filter, setFilter] = useState<(typeof filterLabels)[number]>("全部");
  const clearBothLogs = async () => {
    clearLogs();
    await runCommand("clearLog");
  };
  const visibleLogs = presentEventLogs(logs, filter);
  const listClassName = ["event-list", logPaused ? "paused" : "", visibleLogs.length > 0 ? "has-events" : ""]
    .filter(Boolean)
    .join(" ");

  return (
    <aside className="event-panel" aria-label="事件面板">
      <div className="event-head">
        <h2>事件日志</h2>
        <div className="event-head-actions">
          <Tooltip title="清空事件">
            <button aria-label="清空事件" className="event-clear-btn" onClick={() => void clearBothLogs()} type="button">
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
            <span>{countEventsByFilter(logs, label)}</span>
          </button>
        ))}
      </div>
      <div className={listClassName} role="feed" aria-label="事件流">
        {visibleLogs.length === 0 ? (
          <div className="event-empty">
            <strong>暂无事件</strong>
            <span>运行日志会在这里按时间倒序显示。</span>
          </div>
        ) : (
          visibleLogs.map((entry, index) => (
            <article className={`event-entry ${entry.tone}`} key={`${entry.time}-${entry.title}-${index}`}>
              <span aria-hidden="true" className={`event-dot ${entry.tone}`} />
              <div className="event-body">
                <div className="event-row">
                  <time dateTime={entry.time}>{entry.time}</time>
                  <span className={`event-level ${entry.tone}`}>{entry.label}</span>
                </div>
                <strong>{entry.title}</strong>
                {entry.detail ? <p>{entry.detail}</p> : null}
              </div>
            </article>
          ))
        )}
      </div>
    </aside>
  );
}
