import { useEffect, useState } from "react";
import { MonitorPlay, Radar } from "lucide-react";
import { queryFamily, queryFreshness, queryRouteMatches, selectableQueryTrains, type QueryViews } from "../lib/queryResults";
import type { QueryAttempt, QueryResultRow, RailWatchConfig, RailWatchStatus, SeatAvailability } from "../types";

function timestamp(seconds: number | null) {
  if (seconds === null) return "未知";
  return new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(new Date(seconds * 1000));
}

function seatLabel(seat?: SeatAvailability) {
  if (!seat) return "未知";
  switch (seat.status) {
    case "available": return seat.count === null ? "有票" : `${seat.count} 张`;
    case "unavailable": return "无票";
    case "alternate": return "可候补";
    case "not_applicable": return "不适用";
    default: return "未知";
  }
}

export function QueryResults({ views, rows, status, config, editableRoute, onSelectTrains, now, pending, error, activeQuery }: {
  views: QueryViews; rows: QueryResultRow[]; status: RailWatchStatus; config: RailWatchConfig;
  editableRoute?: RailWatchConfig; onSelectTrains?: (trains: string[]) => void;
  now: number; pending: boolean; error: string | null;
  activeQuery: QueryAttempt | null;
}) {
  const [selectedTrains, setSelectedTrains] = useState<string[]>([]);
  const selectionContext = editableRoute ? queryFamily(editableRoute) : null;
  const selectable = editableRoute ? selectableQueryTrains(views, editableRoute) : new Set<string>();
  const availableTrains = JSON.stringify([...selectable].sort());
  useEffect(() => setSelectedTrains([]), [selectionContext, availableTrains]);
  const validSelection = selectedTrains.filter(train => selectable.has(train));
  const groups = Object.values(views).sort((a, b) => a.latest.conditions.date.localeCompare(b.latest.conditions.date));
  const latest = [...groups].sort((a, b) => b.latest.completed_at - a.latest.completed_at || b.latest.sequence - a.latest.sequence)[0]?.latest;
  return (
    <section className="st-results-panel" aria-label="查询结果">
      <div className="st-panel-head">
        <h3><MonitorPlay size={15} />查询结果</h3>
        <span className="st-result-count">{rows.length} 条</span>
      </div>
      {activeQuery ? <p className="query-context" role="status">当前查询日期：{activeQuery.conditions.date} · 查询中</p> : null}
      {latest ? <p className="query-context">
        {pending ? "手动查询中" : status.monitoring ? "监控运行中" : "当前未监控"}
        {status.monitoring && status.task?.status === "querying" ? " · 正在查询，尚未完成" : ""}
        {` · 最近完成查询日期：${latest.conditions.date}`}
        {(status.task?.next_query_at ?? 0) > now && status.monitoring
          ? ` · 等待下一次查询（${Math.ceil(status.task!.next_query_at! - now)} 秒）` : ""}
      </p> : null}
      {error ? <p className="query-error" role="status">查询未完成：{error}。以下仅为上次保留结果。</p> : null}
      {editableRoute && groups.some(view => !queryRouteMatches(view.latest.conditions, editableRoute))
        ? <p className="query-context" role="status">部分查询结果与当前草稿的路线或日期不一致，无法加入当前草稿。</p> : null}
      {validSelection.length && onSelectTrains ? <button type="button" className="trip-select-results"
        onClick={() => { onSelectTrains(validSelection); setSelectedTrains([]); }}>将选中车次加入行程（{validSelection.length}）</button> : null}
      {groups.map(view => {
        const { latest: attempt, success } = view;
        const routeMatches = Boolean(onSelectTrains && editableRoute &&
          success && queryRouteMatches(success.conditions, editableRoute));
        const selected = attempt.conditions.seat_types;
        const seats = [...new Set([...selected, ...(success?.rows.flatMap(row => Object.entries(row.seats)
          .filter(([, value]) => value.raw || value.status !== "unknown").map(([name]) => name)) ?? [])])];
        return <article className="query-date-group" key={JSON.stringify(attempt.conditions)} aria-label={`${attempt.conditions.date} 查询结果`}>
          <header>
            <strong>{attempt.conditions.date} · {attempt.conditions.from_station} → {attempt.conditions.to_station}</strong>
            <span>{queryFreshness(view, status, config, now, pending)}</span>
            <span>最后成功查询：{timestamp(success?.fetched_at ?? null)}（北京时间）</span>
          </header>
          {attempt.error ? <p className="query-error">{attempt.error}</p> : null}
          {!success ? <p className="query-context">该日期尚无有效查询结果。</p> : success.rows.length === 0
            ? <p className="query-context">上次成功查询未返回车次。</p>
            : <div className="query-table-scroll" tabIndex={0} aria-label={`${attempt.conditions.date} 车次及席别表`}>
              <table className="query-table">
                <thead><tr>{routeMatches ? <th scope="col">选择</th> : null}<th scope="col">车次</th><th scope="col">实际区间</th><th scope="col">出发／到达</th>
                  {seats.map(seat => <th scope="col" className={selected.includes(seat) ? "query-preferred" : undefined} key={seat}>
                    {seat}{selected.includes(seat) ? <small>已选</small> : null}</th>)}
                  <th scope="col">详情</th></tr></thead>
                <tbody>{success.rows.map((row, index) => <tr key={`${row.train}-${row.from_station}-${row.to_station}-${index}`}>
                  {routeMatches ? <td><input type="checkbox" aria-label={`选择 ${attempt.conditions.date} ${row.train} ${row.from_station ?? "未知"}到${row.to_station ?? "未知"}`}
                    checked={validSelection.includes(row.train)} onChange={event => setSelectedTrains(current => event.target.checked
                      ? [...new Set([...current, row.train])] : current.filter(code => code !== row.train))} /></td> : null}
                  <th scope="row">{row.train}</th>
                  <td>{row.from_station ?? "未知"}<br />{row.to_station ?? "未知"}</td>
                  <td>{row.departure_time ?? "未知"}<br />{row.arrival_time ?? "未知"}
                    {row.arrival_time ? <small>{row.arrival_day_offset === null ? "到达日未知" : row.arrival_day_offset === 0 ? "当日到达" : `+${row.arrival_day_offset} 天`}</small> : null}</td>
                  {seats.map(seat => <td key={seat} className={selected.includes(seat) ? "query-preferred" : undefined}>
                    <span className={`query-seat query-seat--${row.seats[seat]?.status ?? "unknown"}`}>{seatLabel(row.seats[seat])}</span>
                  </td>)}
                  <td><details><summary>原始信息</summary><p>{row.raw}</p></details></td>
                </tr>)}</tbody>
              </table>
            </div>}
        </article>;
      })}
      {!groups.length && rows.length > 0 ? <div className="st-dispatch-board">
        <p className="query-context">兼容旧查询数据：席别状态及查询时间未知。</p>
        {rows.map((row, index) => <article className="dispatch-row" key={`${row.date}-${row.train}-${index}`}>
          <strong>{row.train}</strong><span>{row.date ?? "日期未知"} · 状态未知</span>
          <details><summary>原始信息</summary><p className="dispatch-raw">{row.raw}</p></details>
        </article>)}
      </div> : null}
      {!groups.length && !rows.length ? <div className="st-empty-results">
        <Radar size={32} /><strong>暂无查询结果</strong><span>{pending ? "正在查询，请稍候" : "查询余票或启动监控后显示结果与采集时间"}</span>
      </div> : null}
    </section>
  );
}
