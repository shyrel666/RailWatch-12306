/** Evenly spaced ticks from 0 that cover `max`, stepping by 1, 2, 2.5 or 5 × 10ⁿ. */
export function niceTicks(max: number, target = 5): number[] {
  if (!Number.isFinite(max) || max <= 0) return [0, 1];
  const raw = max / target;
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map(m => m * power).find(s => raw <= s * (1 + 1e-9)) ?? 10 * power;
  const count = Math.max(1, Math.ceil(max / step - 1e-9));
  return Array.from({ length: count + 1 }, (_, i) => Number((i * step).toPrecision(12)));
}

/** Axis label for a millisecond tick; the whole axis switches to seconds once it reaches 1 s. */
export function msTick(value: number, ticks: number[]) {
  if (value === 0) return "0";
  if ((ticks.at(-1) ?? 0) < 1000) return `${value}ms`;
  return `${Number((value / 1000).toFixed(2))}s`;
}

export const seconds = (ms: number) => `${(ms / 1000).toFixed(2)} 秒`;
export const millis = (ms: number) => `${ms.toFixed(1)} ms`;

/** Readable span for margins that can run to minutes. */
export function span(ms: number) {
  const total = Math.abs(ms) / 1000;
  if (total < 10) return `${(ms / 1000).toFixed(2)} 秒`;
  if (total < 60) return `${(ms / 1000).toFixed(1)} 秒`;
  const whole = Math.round(total);
  return `${ms < 0 ? "-" : ""}${Math.floor(whole / 60)} 分 ${String(whole % 60).padStart(2, "0")} 秒`;
}
