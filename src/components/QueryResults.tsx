import { useEffect, useMemo, useState } from "react";
import { MonitorPlay, Radar } from "lucide-react";
import { defaultQueryFilter, durationMinutes, filterAndSortRows, formatDuration, isQueryFilterActive, type QueryFilter } from "../lib/queryFilter";
import { queryFamily, queryFreshness, queryRouteMatches, selectableQueryTrains, type QueryViews } from "../lib/queryResults";
import type { PrefillProgress as Progress, QueryAttempt, QueryResultRow, RailWatchConfig, RailWatchStatus, SeatAvailability } from "../types";
import { PrefillProgress } from "./PrefillProgress";

function FilterSelect<T extends string>({ label, value, onChange, options }: {
  label: string; value: T; onChange: (value: T) => void; options: ReadonlyArray<readonly [T, string]>;
}) {
  return <label className="query-filter-field">
    <span>{label}</span>
    <select className="compact-select" aria-label={label} value={value} onChange={event => onChange(event.target.value as T)}>
      {options.map(([key, text]) => <option key={key} value={key}>{text}</option>)}
    </select>
  </label>;
}

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

export function QueryResults({ views, rows, status, config, editableRoute, onSelectTrains, now, pending, error, activeQuery, prefill }: {
  views: QueryViews; rows: QueryResultRow[]; status: RailWatchStatus; config: RailWatchConfig;
  editableRoute?: RailWatchConfig; onSelectTrains?: (trains: string[]) => void;
  now: number; pending: boolean; error: string | null;
  activeQuery: QueryAttempt | null;
  prefill?: Progress | null;
}) {
  const [filter, setFilter] = useState<QueryFilter>(defaultQueryFilter);
  const [selectedTrains, setSelectedTrains] = useState<string[]>([]);
  const selectionContext = editableRoute ? queryFamily(editableRoute) : null;
  const selectable = editableRoute ? selectableQueryTrains(views, editableRoute) : new Set<string>();
  const availableTrains = JSON.stringify([...selectable].sort());
  useEffect(() => setSelectedTrains([]), [selectionContext, availableTrains]);
  const validSelection = selectedTrains.filter(train => selectable.has(train));
  const selectedSet = new Set(validSelection);
  const groups = useMemo(() => Object.values(views).sort((a, b) => a.latest.conditions.date.localeCompare(b.latest.conditions.date)), [views]);
  const sourceRows = useMemo(() => groups.flatMap(view => view.success?.rows ?? []), [groups]);
  const departureStations = useMemo(() => [...new Set(sourceRows.map(row => row.from_station?.trim()).filter((station): station is string => Boolean(station)))], [sourceRows]);
  const fromStation = departureStations.length > 1 && departureStations.includes(filter.fromStation) ? filter.fromStation : "";
  useEffect(() => {
    if (filter.fromStation !== fromStation) setFilter(current => ({ ...current, fromStation }));
  }, [filter.fromStation, fromStation]);
  const changeFilter = <K extends keyof QueryFilter,>(key: K, value: QueryFilter[K]) => setFilter(current => ({ ...current, [key]: value }));
  const canSelectTrains = Boolean(onSelectTrains);
  const filteredGroups = useMemo(() => groups.map(view => ({
    view,
    routeMatches: Boolean(canSelectTrains && editableRoute && view.success && queryRouteMatches(view.success.conditions, editableRoute)),
    visibleRows: view.success ? filterAndSortRows(view.success.rows, { ...filter, fromStation }, view.success.conditions.seat_types) : [],
  })), [groups, canSelectTrains, editableRoute, filter, fromStation]);
  const matchedCount = filteredGroups.reduce((count, { visibleRows }) => count + visibleRows.length, 0);
  const visibleSelectable = new Set(filteredGroups.flatMap(({ visibleRows, routeMatches }) => routeMatches ? visibleRows.map(row => row.train) : []));
  const allVisibleSelected = visibleSelectable.size > 0 && [...visibleSelectable].every(train => selectedSet.has(train));
  const resetFilters = <button type="button" className="query-filter-action" onClick={() => setFilter(defaultQueryFilter)}>重置筛选</button>;
  const latest = [...groups].sort((a, b) => b.latest.completed_at - a.latest.completed_at || b.latest.sequence - a.latest.sequence)[0]?.latest;
  return (
    <section className="st-results-panel" aria-label={prefill ? "购票结果" : "查询结果"}>
      <div className="st-panel-head">
        <h3><MonitorPlay size={15} />{prefill ? "官方预填进度" : "查询结果"}</h3>
        <span className="st-result-count">{prefill ? `${prefill.candidates.length} 个组合` : `${rows.length} 条`}</span>
      </div>
      {prefill ? <PrefillProgress progress={prefill} /> : null}
      {prefill && (groups.length > 0 || rows.length > 0) ? <div className="st-panel-head"><h3>余票查询结果</h3><span>{rows.length} 条</span></div> : null}
      {activeQuery ? <p className="query-context" role="status">当前查询日期：{activeQuery.conditions.date} · 查询中</p> : null}
      {latest && (pending || activeQuery || groups.length > 1) ? <p className="query-context">
        {pending ? "手动查询中 · " : ""}最近完成查询日期：{latest.conditions.date}
      </p> : null}
      {error ? <p className="query-error" role="status">查询未完成：{error}。以下仅为上次保留结果。</p> : null}
      {editableRoute && groups.some(view => !queryRouteMatches(view.latest.conditions, editableRoute))
        ? <p className="query-context" role="status">部分查询结果与当前草稿的路线或日期不一致，无法加入当前草稿。</p> : null}
      {sourceRows.length > 0 ? <>
        <div className="query-filters" role="group" aria-label="查询结果筛选与排序">
          <div className="query-filter-fields">
            <FilterSelect<QueryFilter["category"]> label="车型" value={filter.category} onChange={value => changeFilter("category", value)}
              options={[["all", "全部"], ["highspeed", "高铁动车"], ["normal", "普速"], ["other", "其他"]]} />
            <FilterSelect<QueryFilter["period"]> label="发车时段" value={filter.period} onChange={value => changeFilter("period", value)}
              options={[["all", "全部"], ["night", "凌晨 00–06"], ["morning", "上午 06–12"], ["afternoon", "下午 12–18"], ["evening", "晚间 18–24"]]} />
            <FilterSelect<QueryFilter["availability"]> label="余票状态" value={filter.availability} onChange={value => changeFilter("availability", value)}
              options={[["all", "全部"], ["available", "仅看有票"], ["available_or_alternate", "有票或可候补"]]} />
            {departureStations.length > 1 ? <FilterSelect label="出发站" value={fromStation} onChange={value => changeFilter("fromStation", value)}
              options={[["", "全部"], ...departureStations.map(station => [station, station] as const)]} /> : null}
            <FilterSelect<QueryFilter["sort"]> label="排序方式" value={filter.sort} onChange={value => changeFilter("sort", value)}
              options={[["default", "默认顺序"], ["departure", "发车时间升序"], ["arrival", "到达时间升序"], ["duration", "历时升序"]]} />
          </div>
          <div className="query-filter-summary">
            <span role="status">匹配 {matchedCount} / 总计 {sourceRows.length} 趟</span>
            {matchedCount > 0 && isQueryFilterActive({ ...filter, fromStation }) ? resetFilters : null}
          </div>
        </div>
        {matchedCount === 0 ? <div className="query-filter-empty">
          <p>没有符合筛选条件的车次。</p>{resetFilters}
        </div> : null}
      </> : null}
      {(visibleSelectable.size > 0 || (validSelection.length > 0 && onSelectTrains)) ? <div className="query-result-actions">
        {visibleSelectable.size > 0 ? <button type="button" className="query-filter-action" aria-pressed={allVisibleSelected}
          onClick={() => setSelectedTrains(current => allVisibleSelected
            ? current.filter(train => !visibleSelectable.has(train)) : [...new Set([...current, ...visibleSelectable])])}>
          {allVisibleSelected ? "取消全选" : `全选当前筛选（${visibleSelectable.size}）`}
        </button> : null}
        {validSelection.length > 0 && onSelectTrains ? <button type="button" className="trip-select-results"
          onClick={() => { onSelectTrains(validSelection); setSelectedTrains([]); }}>将选中车次加入行程（{validSelection.length}）</button> : null}
      </div> : null}
      {filteredGroups.map(({ view, routeMatches, visibleRows }) => {
        const { latest: attempt, success } = view;
        if (success?.rows.length && !visibleRows.length && !attempt.error) return null;
        const selected = attempt.conditions.seat_types;
        const seats = [...new Set([...selected, ...(success?.rows.flatMap(row => Object.entries(row.seats)
          .filter(([, value]) => value.raw || value.status !== "unknown").map(([name]) => name)) ?? [])])];
        return <article className="query-date-group" key={JSON.stringify(attempt.conditions)} aria-label={`${attempt.conditions.date} 查询结果`}>
          <header>
            <strong>{attempt.conditions.date} · {attempt.conditions.from_station} → {attempt.conditions.to_station}</strong>
            <span>{queryFreshness(view, status, config, now, pending)}</span>
            <span>最后成功查询：{timestamp(success?.fetched_at ?? null)}</span>
          </header>
          {attempt.error ? <p className="query-error">{attempt.error}</p> : null}
          {!success ? <p className="query-context">该日期尚无有效查询结果。</p> : success.rows.length === 0
            ? <p className="query-context">上次成功查询未返回车次。</p>
            : visibleRows.length > 0 ? <div className="query-table-scroll" tabIndex={0} aria-label={`${attempt.conditions.date} 车次及席别表`}>
              <table className="query-table">
                <thead><tr>{routeMatches ? <th scope="col">选择</th> : null}<th scope="col">车次</th><th scope="col">实际区间</th><th scope="col">出发／到达</th>
                  {seats.map(seat => <th scope="col" className={selected.includes(seat) ? "query-preferred" : undefined} key={seat}>
                    {seat}{selected.includes(seat) ? <small>已选</small> : null}</th>)}
                  <th scope="col">详情</th></tr></thead>
                <tbody>{visibleRows.map((row, index) => {
                  const duration = durationMinutes(row.departure_time, row.arrival_time, row.arrival_day_offset);
                  const arrivalDay = row.arrival_day_offset;
                  return <tr key={`${row.train}-${row.from_station}-${row.to_station}-${index}`}>
                    {routeMatches ? <td><input type="checkbox" aria-label={`选择 ${attempt.conditions.date} ${row.train} ${row.from_station ?? "未知"}到${row.to_station ?? "未知"}`}
                      checked={selectedSet.has(row.train)} onChange={event => setSelectedTrains(current => event.target.checked
                        ? [...new Set([...current, row.train])] : current.filter(code => code !== row.train))} /></td> : null}
                    <th scope="row">{row.train}</th>
                    <td>{row.from_station ?? "未知"}<br />{row.to_station ?? "未知"}</td>
                    <td>{row.departure_time ?? "未知"}<br />{row.arrival_time ?? "未知"}
                      {row.arrival_time ? <small>{typeof arrivalDay !== "number" || !Number.isSafeInteger(arrivalDay) || arrivalDay < 0
                        ? "到达日未知" : arrivalDay === 0 ? "当日到达" : `+${arrivalDay} 天`}</small> : null}
                      {duration === null ? null : <small className="query-duration">历时 {formatDuration(duration)}</small>}</td>
                    {seats.map(seat => <td key={seat} className={selected.includes(seat) ? "query-preferred" : undefined}>
                      <span className={`query-seat query-seat--${row.seats[seat]?.status ?? "unknown"}`}>{seatLabel(row.seats[seat])}</span>
                    </td>)}
                    <td><details><summary>原始信息</summary><p>{row.raw}</p></details></td>
                  </tr>;
                })}</tbody>
              </table>
            </div> : null}
        </article>;
      })}
      {!groups.length && rows.length > 0 ? <div className="st-dispatch-board">
        <p className="query-context">席别状态及查询时间未知。</p>
        {rows.map((row, index) => <article className="dispatch-row" key={`${row.date}-${row.train}-${index}`}>
          <strong>{row.train}</strong><span>{row.date ?? "日期未知"} · 状态未知</span>
          <details><summary>原始信息</summary><p className="dispatch-raw">{row.raw}</p></details>
        </article>)}
      </div> : null}
      {!prefill && !groups.length && !rows.length ? <div className="st-empty-results">
        <Radar size={32} /><strong>暂无查询结果</strong><span>{pending ? "正在查询，请稍候" : "查询余票或启动监控后显示"}</span>
      </div> : null}
    </section>
  );
}
