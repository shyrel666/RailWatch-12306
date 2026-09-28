import { useState } from "react";
import { Button } from "antd";
import { ArrowUpRight, CalendarDays, RefreshCw } from "lucide-react";
import { beijingTimestamp, calendarDays, countdown, presaleDays, SALE_TIME_SOURCE, saleDay, saleStateLabels } from "../lib/saleCalendar";
import { todayIso, isoDaysFromToday, getTripDateStatus } from "../lib/tripDate";
import { useStationSaleTimes } from "../lib/useStationSaleTimes";
import { railwatchApi } from "../lib/railwatchApi";

type Props = { station: string; tripDate: string; windowDays?: number; now: number };
export function SaleCalendar({ station: rawStation, tripDate, windowDays, now }: Props) {
  const station = rawStation.trim();
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
        <h2><CalendarDays size={16} /> 购票日历与起售时间</h2>
        <span className="subtle-label">北京时间 · 含今天 {days} 天</span>
      </div>
      <div className="sale-calendar-body">
        <div className="sale-calendar-dates">
          <p className="sale-calendar-range">当前预售窗口 <strong>{today.slice(5)} — {frontier.slice(5)}</strong></p>
          <p className="sale-calendar-caption">最远日期需等出发站起售；点击日期查看开售安排。</p>
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
          {!station ? <p>在行程设置中填写完整出发站名后，可查询起售时间。</p>
            : loading && !info ? <p>正在核对官方起售时间…</p>
              : issue ? <p className="sale-calendar-warning" role="status">{issue}</p>
                : !detail.time ? <p>暂无适用于该开售日期的明确起售时刻，请前往官方核对。</p> : null}
          <div className="sale-calendar-source">
            <span>来源：12306 起售时间查询</span>
            <span>{info?.checked_at != null ? `获取于 ${beijingTimestamp(info.checked_at * 1000)}` : "尚未取得官方数据"}</span>
            <Button type="text" size="small" onClick={() => {
              setLinkError(false);
              void railwatchApi.openExternal(SALE_TIME_SOURCE)
                .then(result => setLinkError(!result.ok)).catch(() => setLinkError(true));
            }}>前往官方核对 <ArrowUpRight size={13} /></Button>
            {linkError && <span role="status">无法打开浏览器，请在 12306 中查询起售时间。</span>}
          </div>
        </aside>
      </div>
      <p className="sale-calendar-footnote">按预售规则与车站起售时刻计算，不代表当前有余票；实际发售安排以 12306 及车站公告为准。倒计时使用电脑系统时钟。</p>
    </section>
  );
}
