import { useCallback, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { PresentedEvent } from "../lib/formatEventLog";

type Entry = PresentedEvent & { id?: number };
const ESTIMATE = 88;
const OVERSCAN = 5;

function MeasuredEntry({ entry, onHeight }: { entry: Entry; onHeight: (id: number, height: number) => void }) {
  const ref = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const measure = () => onHeight(entry.id!, element.getBoundingClientRect().height);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [entry.id, onHeight]);
  return (
    <article ref={ref} className={`event-entry ${entry.tone}`}>
      <span aria-hidden="true" className={`event-dot ${entry.tone}`} />
      <div className="event-body">
        <div className="event-row"><time dateTime={entry.time}>{entry.time}</time><span className={`event-level ${entry.tone}`}>{entry.label}</span></div>
        <strong>{entry.title}</strong>
        {entry.detail ? <p>{entry.detail}</p> : null}
      </div>
    </article>
  );
}

export function VirtualEventList({ entries, className }: { entries: Entry[]; className: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [viewport, setViewport] = useState({ top: 0, height: 400 });
  const [heights, setHeights] = useState<Map<number, number>>(() => new Map());
  const onHeight = useCallback((id: number, height: number) => {
    if (height <= 0) return;
    setHeights(previous => previous.get(id) === height ? previous : new Map(previous).set(id, height));
  }, []);
  useLayoutEffect(() => {
    const live = new Set(entries.map(entry => entry.id!));
    setHeights(previous => [...previous.keys()].every(id => live.has(id)) ? previous : new Map([...previous].filter(([id]) => live.has(id))));
  }, [entries]);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const update = () => setViewport({ top: element.scrollTop, height: element.clientHeight || 400 });
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    element.addEventListener("scroll", update, { passive: true });
    return () => { observer.disconnect(); element.removeEventListener("scroll", update); };
  }, []);
  const offsets = useMemo(() => {
    const values = [0];
    for (const entry of entries) values.push(values[values.length - 1] + (heights.get(entry.id!) || ESTIMATE));
    return values;
  }, [entries, heights]);
  let first = 0;
  while (first < entries.length && offsets[first + 1] < viewport.top) first++;
  let last = first;
  while (last < entries.length && offsets[last] < viewport.top + viewport.height) last++;
  first = Math.max(0, first - OVERSCAN);
  last = Math.min(entries.length, last + OVERSCAN);
  return (
    <div ref={ref} className={className} role="feed" aria-label="事件流">
      {entries.length === 0 ? <div className="event-empty"><strong>暂无事件</strong><span>运行日志会在这里按时间倒序显示。</span></div> : (
        <div style={{ flexShrink: 0, paddingTop: offsets[first], paddingBottom: offsets[entries.length] - offsets[last] }}>
          {entries.slice(first, last).map(entry => <MeasuredEntry key={entry.id} entry={entry} onHeight={onHeight} />)}
        </div>
      )}
    </div>
  );
}
