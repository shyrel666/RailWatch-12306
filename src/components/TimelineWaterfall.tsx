import type { TimelineSegment } from "../lib/rehearsal";

export function TimelineWaterfall({ segments, prediction = [] }: { segments: TimelineSegment[]; prediction?: TimelineSegment[] }) {
  const known = segments.filter(s => s.duration_ms !== null);
  const total = known.reduce((sum, s) => sum + (s.duration_ms ?? 0), 0);
  const offsets = (items: TimelineSegment[]) => {
    let offset = 0;
    return new Map(items.map(item => { const start = item.start_ms ?? offset; offset = start + (item.duration_ms ?? 0); return [item.id, start]; }));
  };
  const actualOffsets = offsets(segments), predictedOffsets = offsets(prediction);
  const scale = Math.max(1, ...segments.map(s => (actualOffsets.get(s.id) ?? 0) + (s.duration_ms ?? 0)),
    ...prediction.map(s => (predictedOffsets.get(s.id) ?? 0) + (s.duration_ms ?? 0)));
  return <div className="rehearsal-timeline" aria-label="阶段耗时对比">
    {segments.map(segment => {
      const estimate = prediction.find(s => s.id === segment.id)?.duration_ms;
      return <div className="rehearsal-timeline-row" key={segment.id}>
        <span>{segment.label}</span><div className={`rehearsal-track ${segment.duration_ms === null ? "unknown" : ""}`}>
          {estimate != null ? <span className="rehearsal-estimate" style={{ left: `${(predictedOffsets.get(segment.id) ?? 0) / scale * 100}%`, width: `${estimate / scale * 100}%` }} /> : null}
          {segment.duration_ms !== null ? <span className="rehearsal-bar" style={{ left: `${(actualOffsets.get(segment.id) ?? 0) / scale * 100}%`, width: `${segment.duration_ms / scale * 100}%` }} /> : null}
        </div><span>{segment.duration_ms === null ? "未记录" : `${(segment.duration_ms / 1000).toFixed(2)} 秒`}</span>
        <small>{segment.source}</small>
      </div>;
    })}
    <p>已知分段合计 {(total / 1000).toFixed(2)} 秒；未知分段不计入。此图不代表购票成功率或官方处理承诺。</p>
    {prediction.length ? <p>细实条为实际观察，浅色边框为彩排预测；缺少起点时只排列已知分段。</p> : null}
  </div>;
}
