import type { CSSProperties } from "react";
import { Tooltip } from "antd";
import type { TimelineSegment } from "../lib/rehearsal";
import { msTick, niceTicks, seconds } from "../lib/chartScale";

// Bars start where the segment was observed to start; segments without a
// recorded start follow the previous one, so only known spans are drawn.
function offsets(items: TimelineSegment[]) {
  let offset = 0;
  return new Map(items.map(item => {
    const start = item.start_ms ?? offset;
    offset = start + (item.duration_ms ?? 0);
    return [item.id, start];
  }));
}

const pct = (value: number, scale: number) => `${(value / scale) * 100}%`;

/**
 * Gantt-style stage timeline: one row per stage on a shared time axis. The
 * longest known stage carries the accent; a rehearsal prediction, when given,
 * sits behind each bar as a lighter band.
 */
export function TimelineWaterfall({ segments, prediction = [], label = "阶段耗时对比", origin, barLabel = "实际", showSource = false }: {
  segments: TimelineSegment[];
  prediction?: TimelineSegment[];
  label?: string;
  /** Axis caption; set when start times are measured from a fixed origin such as the sale time. */
  origin?: string;
  barLabel?: string;
  showSource?: boolean;
}) {
  const known = segments.filter(s => s.duration_ms !== null);
  const total = known.reduce((sum, s) => sum + (s.duration_ms ?? 0), 0);
  const actualOffsets = offsets(segments), predictedOffsets = offsets(prediction);
  const end = Math.max(0, ...segments.map(s => (actualOffsets.get(s.id) ?? 0) + (s.duration_ms ?? 0)),
    ...prediction.map(s => (predictedOffsets.get(s.id) ?? 0) + (s.duration_ms ?? 0)));
  const ticks = niceTicks(end);
  const scale = ticks.at(-1)!;
  const peak = known.length > 1 ? known.reduce((slowest, s) => s.duration_ms! > slowest.duration_ms! ? s : slowest) : null;
  return <figure className="timing-chart" aria-label={label} style={{ "--intervals": ticks.length - 1 } as CSSProperties}>
    {prediction.length ? <div className="timing-legend" aria-hidden="true">
      <span><i className="timing-key" />{barLabel}</span><span><i className="timing-key ghost" />彩排预测</span>
    </div> : null}
    <ol className="timing-rows">{segments.map(segment => {
      const start = actualOffsets.get(segment.id) ?? 0;
      const forecast = prediction.find(s => s.id === segment.id);
      const estimate = forecast?.duration_ms ?? null;
      const tip = <span className="timing-tip">
        <strong>{segment.duration_ms === null ? "未记录" : seconds(segment.duration_ms)}</strong>
        <span>{segment.label}</span>
        {segment.duration_ms !== null && origin ? <small>{origin} {seconds(start)} 开始</small> : null}
        {estimate !== null ? <small>彩排预测 {seconds(estimate)} · {forecast!.source}</small> : null}
        <small>来源：{segment.source}</small>
      </span>;
      return <li key={segment.id} className={"timing-row" + (segment === peak ? " is-peak" : "") + (segment.duration_ms === null ? " is-unknown" : "")}>
        <span className="timing-label">
          <span>{segment.label}{segment === peak ? <em className="timing-peak">最慢</em> : null}</span>
          {showSource ? <small>{segment.source}</small> : null}
        </span>
        <Tooltip title={tip} placement="top" mouseEnterDelay={0.05}>
          <span className="timing-track" aria-hidden="true">
            {estimate !== null ? <i className="timing-ghost"
              style={{ left: pct(predictedOffsets.get(segment.id) ?? 0, scale), width: pct(estimate, scale) }} /> : null}
            {segment.duration_ms !== null ? <i className="timing-bar"
              style={{ left: pct(start, scale), width: pct(segment.duration_ms, scale) }} /> : null}
          </span>
        </Tooltip>
        <span className="timing-value">
          {segment.duration_ms === null ? "未记录" : seconds(segment.duration_ms)}
          {estimate !== null ? <small>预测 {seconds(estimate)}</small> : null}
        </span>
      </li>;
    })}</ol>
    <div className="timing-axis" aria-hidden="true">
      <span>{origin ?? "按阶段先后"}</span>
      <span className="timing-ticks">{ticks.map(tick => <span key={tick} style={{ left: pct(tick, scale) }}>{msTick(tick, ticks)}</span>)}</span>
    </div>
    <figcaption>已知分段合计 {seconds(total)}；未知分段不计入。此图不代表购票成功率或官方处理承诺。
      {prediction.length ? "深色条为实际观察，浅色底为彩排预测；缺少起点时按阶段先后排列。" : null}</figcaption>
  </figure>;
}
