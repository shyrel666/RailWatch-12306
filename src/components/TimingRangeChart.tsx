import type { CSSProperties } from "react";
import { Tooltip } from "antd";
import { msTick, niceTicks } from "../lib/chartScale";

export type TimingRange = { id: string; label: string; samples: number; median_ms: number; p95_ms: number };

const pct = (value: number, scale: number) => `${(value / scale) * 100}%`;

/**
 * Typical and tail time per row on one axis: the bar runs to the median and a
 * whisker continues to P95. The row with the largest median carries the accent.
 */
export function TimingRangeChart({ rows, label, format }: { rows: TimingRange[]; label: string; format: (ms: number) => string }) {
  const ticks = niceTicks(Math.max(0, ...rows.map(row => Math.max(row.median_ms, row.p95_ms))));
  const scale = ticks.at(-1)!;
  const peak = rows.length > 1 ? rows.reduce((top, row) => row.median_ms > top.median_ms ? row : top) : null;
  return <figure className="timing-chart is-range" aria-label={label} style={{ "--intervals": ticks.length - 1 } as CSSProperties}>
    <div className="timing-legend" aria-hidden="true">
      <span><i className="timing-key" />中位数</span><span><i className="timing-key whisker" />P95</span>
    </div>
    <ol className="timing-rows">{rows.map(row => {
      const tail = Math.max(row.p95_ms, row.median_ms);
      return <li key={row.id} className={"timing-row" + (row === peak ? " is-peak" : "")}>
        <span className="timing-label"><span>{row.label}</span><small>{row.samples} 个样本</small></span>
        <Tooltip placement="top" mouseEnterDelay={0.05} title={<span className="timing-tip">
          <strong>{format(row.median_ms)}</strong><span>{row.label} · 中位数</span>
          <small>P95 {format(row.p95_ms)} · {row.samples} 个样本</small>
        </span>}>
          <span className="timing-track" aria-hidden="true">
            <i className="timing-bar" style={{ left: 0, width: pct(row.median_ms, scale) }} />
            {tail > row.median_ms ? <i className="timing-whisker"
              style={{ left: pct(row.median_ms, scale), width: pct(tail - row.median_ms, scale) }} /> : null}
            <i className="timing-cap" style={{ left: pct(tail, scale) }} />
          </span>
        </Tooltip>
        <span className="timing-value">{format(row.median_ms)}<small>P95 {format(row.p95_ms)}</small></span>
      </li>;
    })}</ol>
    <div className="timing-axis" aria-hidden="true">
      <span />
      <span className="timing-ticks">{ticks.map(tick => <span key={tick} style={{ left: pct(tick, scale) }}>{msTick(tick, ticks)}</span>)}</span>
    </div>
  </figure>;
}
