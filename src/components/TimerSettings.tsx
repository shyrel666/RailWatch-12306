import { Button } from "antd";
import type { RailWatchConfig } from "../types";
import { beijingTimestamp, presaleDays, saleDay } from "../lib/saleCalendar";
import { useClock } from "../lib/useClock";
import { useStationSaleTimes } from "../lib/useStationSaleTimes";
import { PreferenceSection } from "./PreferenceSection";

export function TimerSettings({ config, update, windowDays }: {
  config: RailWatchConfig;
  update: (patch: Partial<RailWatchConfig>) => void;
  windowDays?: number;
}) {
  const now = useClock();
  const station = config.from_station_cn.trim();
  const { info, loading, error, refresh } = useStationSaleTimes(station);
  const detail = saleDay(config.date, now, presaleDays(windowDays), info);
  const target = config.sale_at?.endsWith("+08:00") ? Date.parse(config.sale_at) : NaN;
  const validTarget = Number.isFinite(target);
  const canApply = !loading && !error && detail.saleAt !== null && detail.saleAt > now;
  const released = detail.state === "window" || detail.state === "open";
  const usingSaleTime = config.timer_enabled && canApply && target === detail.saleAt;
  const summary = !config.timer_enabled ? "立即开始 · 点击开始监控后直接查询"
    : !validTarget ? "定时开始 · 请选择开始时间"
      : target <= now ? "指定时间已到 · 点击开始监控后直接查询"
        : `定时开始 · ${beijingTimestamp(target)}（北京时间）`;
  const guidance = !station ? "填写出发站和乘车日期后，可查看起售安排。"
    : detail.state === "invalid" ? "请先填写有效的乘车日期。"
      : detail.state === "expired" ? "乘车日期已过，请先调整行程。"
        : released ? "已进入预售期，建议立即开始监控，无需填写定时时间。"
          : loading ? "正在查询起售时间…"
            : error || (canApply ? `预计 ${beijingTimestamp(detail.saleAt!)} 起售（北京时间）。`
              : "暂未查到明确起售时间。可刷新重试，或按官方公告手动设置。");
  const saleTimePatch = (): Partial<RailWatchConfig> | null => {
    const current = saleDay(config.date, Date.now(), presaleDays(windowDays), info);
    if (!canApply || current.saleAt === null || current.saleAt <= Date.now() || info?.checked_at == null) return null;
    return {
      timer_enabled: true,
      sale_at: `${current.releaseDate}T${current.time}:00+08:00`,
      target_time: `${current.time}:00`,
      sale_time_source: "12306",
      sale_time_checked_at: new Date(info.checked_at * 1000).toISOString(),
    };
  };
  const applySaleTime = () => {
    const patch = saleTimePatch();
    if (patch) update(patch);
  };
  const selectTimer = () => {
    // Retain a future custom time when switching modes; otherwise suggest the current trip's release.
    update((!validTarget || target <= now ? saleTimePatch() : null) ?? { timer_enabled: true });
  };

  return <PreferenceSection id="trip-timer" title="定时启动" description={summary}>
    <div className="timer-mode-options" role="radiogroup" aria-label="开始方式">
      <label className={`timer-mode${!config.timer_enabled ? " selected" : ""}`}>
        <input type="radio" name="timer-mode" aria-label="立即开始" checked={!config.timer_enabled}
          onChange={() => update({ timer_enabled: false })} />
        <span><strong>立即开始</strong><small>点击开始监控后直接查询</small></span>
      </label>
      <label className={`timer-mode${config.timer_enabled ? " selected" : ""}`}>
        <input type="radio" name="timer-mode" aria-label="定时开始" checked={config.timer_enabled}
          onChange={selectTimer} />
        <span><strong>定时开始</strong><small>提前准备，到指定时间查询</small></span>
      </label>
    </div>
    <div className="timer-trip-status">
      <div className="timer-trip-heading">
        <span>{station || "未设置出发站"} · {config.date || "未设置乘车日期"} 乘车</span>
        {station && <Button type="text" size="small" aria-label="刷新起售时间" loading={loading} onClick={refresh}>刷新</Button>}
      </div>
      <p role="status">{guidance}</p>
      {canApply && (usingSaleTime ? <small className="timer-applied">已使用当前行程起售时间</small>
        : <Button size="small" onClick={applySaleTime}>设为起售时间</Button>)}
      {released && config.timer_enabled && <Button size="small" onClick={() => update({ timer_enabled: false })}>改为立即开始</Button>}
      {!released && canApply && <small>起售时间来源：12306</small>}
    </div>
    {config.timer_enabled && <>
      <label className="trip-field">
        <span>开始日期时间（北京时间）</span>
        <input aria-label="定时启动时间" aria-describedby="timer-time-help" className="native-input" type="datetime-local" step="1"
          value={config.sale_at?.replace(/\+08:00$/, "") || ""}
          onChange={event => update({
            sale_at: event.target.value ? `${event.target.value}+08:00` : "",
            target_time: event.target.value.slice(11),
            sale_time_source: "manual",
            sale_time_checked_at: new Date().toISOString(),
          })} />
      </label>
      <p id="timer-time-help">{!validTarget ? "请选择希望开始查询的日期和时间。"
        : target <= now ? "这个时间已经到了。点击开始监控会直接查询，也可修改为未来时间。"
          : `将于 ${beijingTimestamp(target)} 开始查询。可在上方手动修改。`}</p>
      {config.sale_time_source === "12306" && canApply && !usingSaleTime && <p className="trip-date-warning" role="status">
        当前设置与此行程的起售时间不同，请点击“设为起售时间”更新，或手动修改。
      </p>}
      <p>点击“开始监控”后立即准备查询页，到设定时刻才发起查询，不会固定提前两秒。请保持程序运行，并在启动任务前完成登录和系统自动对时。</p>
      <p>启用自动提交或自动候补时，会在起售前一分钟内补查一次登录；无法确认则暂停并提醒。最后10秒不发起登录检查。</p>
      <p>彩排中的时间偏差仅供检查，不会自动补偿查询时刻；测量误差过大时会显示“无法判断”。</p>
    </>}
  </PreferenceSection>;
}
