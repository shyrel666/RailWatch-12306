import { useEffect, useState } from "react";
import { Button, Select, Switch } from "antd";
import { Clock3, Plus, RefreshCw, Trash2 } from "lucide-react";
import { Hint } from "./DisplayPrimitives";
import type { AlternateOptionsResult, NewTrainWindow, RailWatchConfig } from "../types";
import { DEFAULT_ALTERNATE_DEADLINE, alternateConfigIssue, alternateDates, canonicalDeadline, deadlineMinutes,
  officialReadTime } from "../lib/alternateOptions";
import type { CommandRunner } from "./componentTypes";

export function AlternateSettings({ config, update, runCommand, disabled }: {
  config: RailWatchConfig; update: (patch: Partial<RailWatchConfig>) => void;
  runCommand: CommandRunner; disabled: boolean;
}) {
  const [read, setRead] = useState<AlternateOptionsResult>({ snapshot: null, warning: null });
  const [reading, setReading] = useState(false);
  useEffect(() => {
    let current = true;
    void runCommand<AlternateOptionsResult>("readAlternateOptions").then(result => {
      if (current && result) setRead(result);
    });
    return () => { current = false; };
  }, [runCommand]);
  const refresh = async () => {
    setReading(true);
    try {
      const result = await runCommand<AlternateOptionsResult>("readAlternateOptions", { refresh: true,
        from_station: config.from_station_cn.trim(), to_station: config.to_station_cn.trim() });
      if (result) setRead(result);
    } finally { setReading(false); }
  };
  const dates = alternateDates(config);
  const snapshot = read.snapshot;
  const sameRoute = (from?: string, to?: string) =>
    from === config.from_station_cn.trim() && to === config.to_station_cn.trim();
  // A city-level trip (北京) is recorded with the stations it was read for, not just the actual ones (北京南).
  const matches = Boolean(snapshot && (sameRoute(snapshot.from_station, snapshot.to_station) ||
    sameRoute(snapshot.trip_from_station, snapshot.trip_to_station)) &&
    snapshot.dates?.length && snapshot.dates.every(date => dates.includes(date)));
  const values = matches ? [...new Set((snapshot?.deadline_options ?? []).map(canonicalDeadline))] : [];
  const deadline = canonicalDeadline(config.alternate_deadline);
  const offered = values.includes(deadline);
  // An unsupported legacy value (e.g. an old absolute time) needs a way out before any official read.
  const fallback = !values.length && !deadlineMinutes(deadline) ? DEFAULT_ALTERNATE_DEADLINE : null;
  const windows = config.alternate_new_train_windows ?? [];
  const changeWindow = (index: number, patch: Partial<NewTrainWindow>) => update({
    alternate_new_train_windows: windows.map((w, i) => i === index ? { ...w, ...patch } : w),
  });
  const unusedDate = dates.find(date => !windows.some(w => w.date === date));
  const issue = alternateConfigIssue(config);
  return <section className="alternate-settings alternate-config-section" aria-label="兑现条件">
    <div className="alternate-config-heading"><Clock3 size={16} aria-hidden="true" /><h3>兑现条件</h3></div>
    {config.seat_keyword.split(/[,，、;；\s]+/).some(seat => seat === "硬卧" || seat === "软卧") ?
      <p className="trip-automation-help">卧铺候补的上／中／下铺由官网分配。</p> : null}
    <div className="alternate-config-row">
      <div className="alternate-config-copy">
        <span className="trip-field-label-with-help">截止兑现时间
          <Hint text="只能选择官网候补表单提供的选项。提交前会再次读取核对；选项不可用时暂停提交，保留原方案供重选。" /></span>
        <p>使用官网提供的截止时间，提交前会再次核对。</p>
      </div>
      <div className="trip-field alternate-deadline">
        <span className="trip-input-with-action">
          <Select aria-label="截止兑现时间" className="trip-select" showSearch={false} value={deadline || undefined}
            placeholder="请同步官网选项" notFoundContent="尚未读取官网选项"
            options={[...(!offered && deadline ? [{ value: deadline, label: `${deadline}（待核对）`, disabled: true }] : []),
              ...(fallback ? [{ value: fallback, label: `${fallback}（提交前核对官网选项）` }] : []),
              ...values.map(value => ({ value, label: value }))]}
            onChange={value => update({ alternate_deadline: value })} />
          <Button aria-label="同步官网截止选项" icon={<RefreshCw size={14} />} disabled={disabled} loading={reading}
            onClick={() => void refresh()}>同步</Button>
        </span>
        <small className={`field-help alternate-deadline-status${read.snapshot && !matches ? " pending" : ""}`}>
          {!read.snapshot ? "尚未同步，进入候补表单时自动核对"
            : matches ? `已同步 · ${officialReadTime(read.snapshot.observed_at)}`
              : "路线或日期已变更，请重新同步"}
        </small>
      </div>
    </div>
    {!offered && values.length > 0 ? <p role="alert">已保存的截止兑现时间不在这次官网选项中，请重新选择。</p> : null}
    {read.warning ? <p role="status">{read.warning}</p> : null}
    <div className="alternate-config-row">
      <div className="alternate-config-copy">
        <span className="trip-field-label-with-help">接受新增列车
          <Hint text={`在所选日期和时段内，按 ${config.from_station_cn || "出发站"} → ${config.to_station_cn || "到达站"}（含同城站）及已选席别兑现新增列车；票价高于预付款时官网不予兑现。只对候补方案包含的日期生效；最多 3 个日期，0–24 点表示全天。`} />
        </span>
        <p>扩大候补范围，接受符合路线、席别与时段的新增列车。</p>
      </div>
      <div className="alternate-config-switch-control">
        <Switch aria-label="接受新增列车" checked={config.alternate_accept_new_trains ?? false}
          onChange={checked => update({ alternate_accept_new_trains: checked })} />
      </div>
    </div>
    {config.alternate_accept_new_trains ? <div className="alternate-new-train-windows">
      <div className="alternate-window-heading"><span>可接受的出发时段</span><small>0–24 点表示全天</small></div>
      {windows.map((window, index) => <div className="alternate-window" key={index}>
        <label className="trip-field"><span>日期 {index + 1}</span>
          <Select aria-label={`新增列车日期 ${index + 1}`} value={window.date}
            options={[...new Set([...dates, window.date])].map(date => ({ value: date, label: date,
              disabled: !dates.includes(date) || windows.some((w, i) => i !== index && w.date === date) }))}
            onChange={date => changeWindow(index, { date })} />
        </label>
        <label className="trip-field"><span>最早出发</span><Select aria-label={`最早出发 ${index + 1}`} value={window.start_hour}
          options={Array.from({ length: 24 }, (_, hour) => ({ value: hour, label: `${hour}点`, disabled: hour >= window.end_hour }))}
          onChange={start_hour => changeWindow(index, { start_hour })} /></label>
        <label className="trip-field"><span>最晚出发</span><Select aria-label={`最晚出发 ${index + 1}`} value={window.end_hour}
          options={Array.from({ length: 24 }, (_, i) => ({ value: i + 1, label: `${i + 1}点`, disabled: i + 1 <= window.start_hour }))}
          onChange={end_hour => changeWindow(index, { end_hour })} /></label>
        <Button type="text" danger icon={<Trash2 size={14} />} aria-label={`删除新增列车日期 ${index + 1}`}
          onClick={() => update({ alternate_new_train_windows: windows.filter((_, i) => i !== index) })} />
      </div>)}
      <Button className="alternate-window-add" icon={<Plus size={14} />} disabled={windows.length >= 3 || !unusedDate} onClick={() => {
        if (unusedDate) update({ alternate_new_train_windows: [...windows, { date: unusedDate, start_hour: 0, end_hour: 24 }] });
      }}>添加新增列车日期</Button>
    </div> : null}
    {issue ? <p role="alert">{issue}</p> : null}
  </section>;
}
