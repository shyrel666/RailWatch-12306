import type { QueryResultRow, SeatAvailability, StructuredQueryResultRow } from "../types";

export type TrainCategory = "highspeed" | "normal" | "other";
export type DeparturePeriod = "night" | "morning" | "afternoon" | "evening";

export type QueryFilter = {
  category: TrainCategory | "all";
  period: DeparturePeriod | "all";
  availability: "all" | "available" | "available_or_alternate";
  fromStation: string;
  sort: "default" | "departure" | "arrival" | "duration";
};

export const defaultQueryFilter: Readonly<QueryFilter> = Object.freeze({
  category: "all",
  period: "all",
  availability: "all",
  fromStation: "",
  sort: "default",
});

export function isQueryFilterActive(filter: QueryFilter): boolean {
  return filter.category !== "all" || filter.period !== "all" || filter.availability !== "all" ||
    filter.fromStation !== "" || filter.sort !== "default";
}

type ClockTime = string | null | undefined;

function clockMinutes(time: ClockTime): number | null {
  const match = /^([01]\d|2[0-3]):([0-5]\d)$/.exec(time ?? "");
  return match ? Number(match[1]) * 60 + Number(match[2]) : null;
}

function arrivalMinutes(time: ClockTime, dayOffset: number | null | undefined): number | null {
  const clock = clockMinutes(time);
  if (clock === null || typeof dayOffset !== "number" || !Number.isSafeInteger(dayOffset) || dayOffset < 0) return null;
  const minutes = dayOffset * 24 * 60 + clock;
  return Number.isSafeInteger(minutes) ? minutes : null;
}

export function durationMinutes(departure: ClockTime, arrival: ClockTime, dayOffset?: number | null): number | null {
  const start = clockMinutes(departure);
  const end = arrivalMinutes(arrival, dayOffset);
  return start === null || end === null || end <= start ? null : end - start;
}

export function formatDuration(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  const remaining = minutes % 60;
  if (!hours) return `${minutes}分钟`;
  return remaining ? `${hours}小时${remaining}分` : `${hours}小时`;
}

export function trainCategory(trainCode: string, seats?: Record<string, SeatAvailability>): TrainCategory {
  switch (trainCode.trim().toUpperCase()[0]) {
    case "X":
    case "G":
    case "D":
    case "C":
    case "S":
      return "highspeed";
    case "Z":
    case "N":
    case "V":
      return "normal";
    case "T":
    case "K": {
      const hasSeat = (name: string) => {
        const status = seats?.[name]?.status;
        return status === "available" || status === "unavailable" || status === "alternate";
      };
      const conventional = ["硬座", "硬卧"].some(hasSeat);
      const highspeed = ["商务座", "特等座", "一等座", "二等座", "动卧"].some(hasSeat);
      return conventional && !highspeed ? "normal" : "highspeed";
    }
    default:
      return "other";
  }
}

const departurePeriods = ["night", "morning", "afternoon", "evening"] as const;

export function departurePeriod(time?: string | null): DeparturePeriod | null {
  const minutes = clockMinutes(time);
  return minutes === null ? null : departurePeriods[Math.floor(minutes / (6 * 60))];
}

type FilterableRow = QueryResultRow & Partial<Pick<StructuredQueryResultRow,
  "from_station" | "departure_time" | "arrival_time" | "arrival_day_offset" | "seats"
>>;

function sortValue(row: FilterableRow, sort: Exclude<QueryFilter["sort"], "default">): number | null {
  switch (sort) {
    case "departure": return clockMinutes(row.departure_time);
    case "arrival": return arrivalMinutes(row.arrival_time, row.arrival_day_offset);
    case "duration": return durationMinutes(row.departure_time, row.arrival_time, row.arrival_day_offset);
  }
}

export function filterAndSortRows<Row extends FilterableRow>(
  rows: readonly Row[], filter: QueryFilter, selectedSeats: readonly string[],
): Row[] {
  const { category, period, availability, fromStation, sort } = filter;
  const matching = rows.filter(row => {
    if (category !== "all" && trainCategory(row.train, row.seats) !== category) return false;
    if (period !== "all" && departurePeriod(row.departure_time) !== period) return false;
    if (fromStation && row.from_station?.trim() !== fromStation) return false;
    if (availability === "all") return true;
    return Object.entries(row.seats ?? {}).some(([seat, value]) =>
      (!selectedSeats.length || selectedSeats.includes(seat)) &&
      (value.status === "available" || (availability === "available_or_alternate" && value.status === "alternate")));
  });
  if (sort === "default") return matching;
  return matching
    .map(row => ({ row, value: sortValue(row, sort) ?? Infinity }))
    .sort((a, b) => a.value === b.value ? 0 : a.value - b.value)
    .map(({ row }) => row);
}
