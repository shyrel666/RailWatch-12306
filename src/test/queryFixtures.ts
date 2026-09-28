import { defaultConfig } from "../store/railwatchStore";
import type { QuerySnapshot } from "../types";

export const queryConfig = { ...defaultConfig, from_station_cn: "北京", to_station_cn: "上海", date: "2026-09-22",
  date_range: "±1天", train_code: "G101", seat_keyword: "二等座,一等座", query_timeout: 5, interval: 3 };
export const queryTime = Date.parse("2026-09-22T13:00:00Z") / 1000;
export function querySnapshot(patch: Partial<QuerySnapshot> = {}): QuerySnapshot {
  return { schema_version: 1, run_id: "run", query_id: "q1", sequence: 1,
    conditions: { from_station: "北京", to_station: "上海", date: queryConfig.date, train_codes: ["G101"], seat_types: ["二等座", "一等座"] },
    fetched_at: queryTime, completed_at: queryTime, status: "success", error: null,
    rows: [{ train: "G101", date: queryConfig.date, from_station: "张家界西", to_station: "上海虹桥",
      departure_time: "23:00", arrival_time: "07:00", arrival_day_offset: null, raw: "张家界西 无座 备注：有变化",
      seats: { "二等座": { status: "available", count: 3, raw: "3" }, "一等座": { status: "unavailable", count: 0, raw: "无" },
        "无座": { status: "alternate", count: null, raw: "候补" }, "软卧": { status: "unknown", count: null, raw: "--" } } }], ...patch };
}
