import { Button, Popconfirm } from "antd";
import type { RenumberCandidate } from "../types";
import { queryTargets, renumberTimetable } from "../lib/queryResults";

type Suggestion = { train: string; date: string; candidates?: RenumberCandidate[] };

/** Listed trains matching a saved number's last-seen timetable. Replacing needs a confirmation per pair. */
export function RenumberSuggestions({ items, trainCode, onReplace }: {
  items: Suggestion[];
  trainCode: string;
  onReplace: (from: string, to: string) => void;
}) {
  const saved = queryTargets(trainCode.toUpperCase());
  const pairs = new Map<string, { from: string; candidate: RenumberCandidate; dates: string[] }>();
  for (const item of items) for (const candidate of item.candidates ?? []) {
    const key = `${item.train}>${candidate.train}`;
    const pair = pairs.get(key) ?? { from: item.train, candidate, dates: [] };
    pairs.set(key, { ...pair, dates: [...pair.dates, item.date] });
  }
  if (!pairs.size) return null;
  return (
    <ul className="renumber-list" aria-label="可能的新车次">
      {[...pairs.entries()].map(([key, { from, candidate, dates }]) => (
        <li key={key}>
          <span>
            <strong className="mono">{from} → {candidate.train}</strong>
            {" "}{renumberTimetable(candidate)}，与 {candidate.seen_date} 记录的 {from} 一致（{dates.join("、")} 未查到 {from}）
          </span>
          {saved.includes(from) ? (
            <Popconfirm
              title={`替换为 ${candidate.train}？`}
              description={`把行程车次和本路线收藏里的 ${from} 换成 ${candidate.train}。请先在官方页面核对两趟车的站名和时刻。`}
              okText="替换"
              cancelText="取消"
              onConfirm={() => onReplace(from, candidate.train)}
            >
              <Button size="small">替换为 {candidate.train}</Button>
            </Popconfirm>
          ) : <small>行程车次中已没有 {from}</small>}
        </li>
      ))}
    </ul>
  );
}
