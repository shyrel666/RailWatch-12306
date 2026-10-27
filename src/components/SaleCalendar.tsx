import { useState } from "react";
import { Button } from "antd";
import { ArrowUpRight, BellPlus, BellRing, CalendarDays, RefreshCw, X } from "lucide-react";
import { beijingTimestamp, calendarDays, countdown, presaleDays, SALE_TIME_SOURCE, saleDay, saleStateLabels } from "../lib/saleCalendar";
import { todayIso, isoDaysFromToday, getTripDateStatus } from "../lib/tripDate";
import { useStationSaleTimes } from "../lib/useStationSaleTimes";
import { useSaleReminders } from "../lib/useSaleReminders";
import { IDLE_POLICY } from "../lib/idlePolicy";
import { railwatchApi } from "../lib/railwatchApi";
import { Hint } from "./DisplayPrimitives";

type Props = { station: string; destination?: string; tripDate: string; windowDays?: number; now: number };
export function SaleCalendar({ station: rawStation, destination: rawDestination = "", tripDate, windowDays, now }: Props) {
  const station = rawStation.trim();
  const destination = rawDestination.trim();
  const reminders = useSaleReminders(Boolean(station && destination));
  const days = presaleDays(windowDays);
  const today = todayIso(new Date(now));
  const dates = calendarDays(now, days);
  const frontier = isoDaysFromToday(days - 1, new Date(now));
  const validTrip = getTripDateStatus(tripDate, new Date(now), days).daysFromToday !== null;
  const [selection, setSelection] = useState<{ key: string; date: string } | null>(null);
  const key = `${station}/${tripDate}/${today}`;
  const selected = selection?.key === key ? selection.date : validTrip ? tripDate : frontier;
  const { info, loading, error, refresh } = useStationSaleTimes(station);
  const detail = saleDay(selected, now, days, info);
  const [linkError, setLinkError] = useState(false);
  const outdated = info?.expires_at !== null && info?.expires_at !== undefined && now / 1000 >= info.expires_at;
  const issue = error || info?.warning || (outdated ? "起售数据已过期，请刷新后核对。" : null);
  return (
    <section className="sale-calendar" aria-label="购票日历与起售时间">
      <div className="section-heading">
        <h2><CalendarDays size={16} /> 购票日历
          <Hint text="按预售规则与车站起售时刻推算，不代表当前有余票；实际安排以 12306 及车站公告为准。倒计时使用电脑系统时钟。" /></h2>
        <span className="subtle-label">预售期 <strong className="mono">{today.slice(5)} — {frontier.slice(5)}</strong> · {days} 天</span>
      </div>
      <div className="sale-calendar-body">
        <div className="sale-calendar-dates">
          <div className="sale-calendar-grid" role="group" aria-label="乘车日期">
            {dates.map(date => {
              const day = saleDay(date, now, days, info);
              const label = saleStateLabels[day.state];
              return <button key={date} type="button"
                className={`sale-calendar-day ${day.state}${date === selected ? " selected" : ""}`}
                aria-label={`${date} ${label}${date === tripDate ? " 当前行程" : ""}`}
                aria-pressed={date === selected} onClick={() => setSelection({ key, date })}>
                <span>{date === today ? "今天" : `周${"日一二三四五六"[new Date(`${date}T00:00:00Z`).getUTCDay()]}`}{date === tripDate ? " · 行程" : ""}</span>
                <strong>{Number(date.slice(5, 7))}/{Number(date.slice(8))}</strong>
                <small>{label}</small>
              </button>;
            })}
          </div>
        </div>
        <aside className="sale-calendar-detail" aria-label="所选日期起售安排">
          <div className="sale-calendar-station"><strong>{station ? `${station} · 出发站` : "请先设置出发站"}</strong>
            <Button type="text" size="small" aria-label="刷新起售时间" title="刷新官方起售时间" disabled={!station}
              loading={loading} icon={<RefreshCw size={14} />} onClick={refresh} />
          </div>
          <span className="subtle-label">乘车日期 · {selected}{selected === tripDate ? " · 当前行程" : ""}</span>
          {validTrip && selected !== tripDate && <Button type="link" size="small" onClick={() => setSelection(null)}>返回行程日期</Button>}
          {detail.releaseDate && <p className="sale-calendar-release">对应开售日 <strong>{detail.releaseDate}</strong></p>}
          <div className="sale-calendar-time">{detail.time || "时间待核对"}</div>
          <span className={`sale-calendar-status ${detail.state}`}>{saleStateLabels[detail.state]}</span>
          {detail.saleAt !== null && detail.saleAt > now && detail.state !== "expired" && <p className="sale-calendar-countdown">
            距起售 <strong>{countdown(detail.saleAt, now)}</strong>
          </p>}
          {station && destination && detail.saleAt !== null && detail.saleAt > now ? (
            <SaleReminderControl station={station} destination={destination} date={selected} reminders={reminders} />
          ) : null}
          {!station ? <p>在行程设置中填写出发站后显示起售时间。</p>
            : loading && !info ? <p>正在核对官方起售时间…</p>
              : issue ? <p className="sale-calendar-warning" role="status">{issue}</p>
                : !detail.time ? <p>暂无该日的明确起售时刻，请前往官方核对。</p> : null}
          <div className="sale-calendar-source">
            <span>{info?.checked_at != null ? `12306 · 获取于 ${beijingTimestamp(info.checked_at * 1000)}` : "尚未取得官方数据"}</span>
            <Button type="text" size="small" onClick={() => {
              setLinkError(false);
              void railwatchApi.openExternal(SALE_TIME_SOURCE)
                .then(result => setLinkError(!result.ok)).catch(() => setLinkError(true));
            }}>前往官方核对 <ArrowUpRight size={13} /></Button>
            {linkError && <span role="status">无法打开浏览器，请在 12306 中查询起售时间。</span>}
          </div>
        </aside>
      </div>
    </section>
  );
}

function SaleReminderControl({ station, destination, date, reminders }: {
  station: string; destination: string; date: string; reminders: ReturnType<typeof useSaleReminders>;
}) {
  const lead = reminders.list?.lead_minutes ?? IDLE_POLICY.sale_reminder_lead_minutes;
  const items = reminders.list?.items ?? [];
  const current = items.find(item => item.from_station === station && item.to_station === destination && item.date === date);
  const others = items.filter(item => item !== current);
  return (
    <div className="sale-calendar-reminder" aria-label="起售提醒">
      {current ? <span className="sale-calendar-reminder-set">
        <BellRing size={13} aria-hidden="true" />
        {current.notified_at !== null ? "已发送起售提醒" : `将在起售前 ${lead} 分钟提醒`}
        <Button type="link" size="small" disabled={reminders.busy} onClick={() => void reminders.remove(current.id)}>取消提醒</Button>
      </span> : <Button size="small" icon={<BellPlus size={13} />} loading={reminders.busy} disabled={!reminders.list}
        onClick={() => void reminders.add(station, destination, date)}>起售前 {lead} 分钟提醒我</Button>}
      <small>不用先建任务；按通知设置推送到桌面和手机。</small>
      {reminders.error && <span className="sale-calendar-warning" role="alert">{reminders.error}</span>}
      {others.length ? <ul aria-label="其他起售提醒">
        {others.map(item => <li key={item.id}>
          <span>{item.from_station}→{item.to_station} {item.date.slice(5)} · {beijingTimestamp(item.sale_at * 1000).slice(5, 16)} 起售</span>
          <Button type="text" size="small" aria-label={`取消 ${item.from_station}→${item.to_station} ${item.date} 的起售提醒`}
            disabled={reminders.busy} icon={<X size={12} />} onClick={() => void reminders.remove(item.id)} />
        </li>)}
      </ul> : null}
    </div>
  );
}
