// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { QueryResults } from "./QueryResults";
import { defaultStatus } from "../store/railwatchStore";
import { queryConfig, querySnapshot, queryTime } from "../test/queryFixtures";
import { queryRows, type QueryViews } from "../lib/queryResults";
import type { StructuredQueryResultRow } from "../types";

afterEach(cleanup);

function show(views: QueryViews, overrides: Partial<Parameters<typeof QueryResults>[0]> = {}) {
  return render(<QueryResults views={views} rows={queryRows(views)} config={queryConfig} status={defaultStatus}
    now={queryTime} pending={false} error={null} activeQuery={null} {...overrides} />);
}

test("inventory is displayed per seat with counts and explicit selected columns", () => {
  const snap = querySnapshot();
  show({ one: { owner: "run", latest: snap, success: snap } });
  expect(screen.getByRole("columnheader", { name: /二等座.*已选/ })).toBeTruthy();
  expect(screen.getByText("3 张")).toBeTruthy();
  expect(screen.getByText("无票")).toBeTruthy();
  expect(screen.getByText("可候补")).toBeTruthy();
  expect(screen.getByRole("cell", { name: /张家界西.*上海虹桥/ })).toBeTruthy();
  expect(screen.getByText("到达日未知")).toBeTruthy();
  expect(screen.getByText(/最后成功查询：.*21:00:00/)).toBeTruthy();
  expect(screen.getByText(/上次成功结果 · 当前未监控/)).toBeTruthy();
});

test("same train on two dates is grouped separately with its own timestamp", () => {
  const first = querySnapshot();
  const second = querySnapshot({ conditions: { ...first.conditions, date: "2026-09-23" }, fetched_at: queryTime + 20, sequence: 2 });
  show({ first: { owner: "run", latest: first, success: first }, second: { owner: "run", latest: second, success: second } });
  const group = screen.getByRole("article", { name: "2026-09-23 查询结果" });
  expect(within(group).getByText("G101")).toBeTruthy();
  expect(within(group).getByText(/21:00:20/)).toBeTruthy();
  expect(screen.getAllByText("G101")).toHaveLength(2);
});

test("failure explains retained rows and never claims a new successful timestamp", () => {
  const success = querySnapshot();
  const latest = querySnapshot({ status: "error", error: "HTTP 429，请等待", fetched_at: null, rows: [], sequence: 2 });
  show({ one: { owner: "run", latest, success } });
  expect(screen.getByText("本轮查询失败 · 显示上次成功结果")).toBeTruthy();
  expect(screen.getByText("HTTP 429，请等待")).toBeTruthy();
  expect(screen.getByText("3 张")).toBeTruthy();
  expect(screen.getByText(/最后成功查询：.*21:00:00/)).toBeTruthy();
});

test("empty successful results and failures without success are distinguishable", () => {
  const empty = querySnapshot({ rows: [] });
  const failure = querySnapshot({ conditions: { ...empty.conditions, date: "2026-09-23" }, status: "error", error: "超时", fetched_at: null, rows: [] });
  show({ one: { owner: "run", latest: empty, success: empty }, two: { owner: "run", latest: failure, success: null } });
  expect(screen.getByText("上次成功查询未返回车次。")).toBeTruthy();
  expect(screen.getByText("该日期尚无有效查询结果。")).toBeTruthy();
});

test("legacy raw text containing 张 or 有 cannot produce an availability badge", () => {
  const { container } = show({}, { rows: [{ train: "G1", raw: "张家界 无座 有" }] });
  expect(screen.getByText(/日期未知 · 状态未知/)).toBeTruthy();
  expect(container.querySelector(".query-seat--available")).toBeNull();
  expect(screen.queryByText("有票")).toBeNull();
});

test("current query date is independent from the last completed date", () => {
  const snap = querySnapshot();
  show({ one: { owner: "run", latest: snap, success: snap } }, {
    status: { ...defaultStatus, monitoring: true },
    activeQuery: { ...snap, query_id: "next", sequence: 2, conditions: { ...snap.conditions, date: "2026-09-23" }, started_at: queryTime },
  });
  expect(screen.getByText("当前查询日期：2026-09-23 · 查询中")).toBeTruthy();
  expect(screen.getByText(/最近完成查询日期：2026-09-22/)).toBeTruthy();
});

test("actual station results can be chosen only from the current route and date", async () => {
  const user = userEvent.setup();
  const current = querySnapshot();
  const other = querySnapshot({ conditions: { ...current.conditions, from_station: "广州" }, sequence: 2 });
  const onSelectTrains = vi.fn();
  show({ current: { owner: "run", latest: current, success: current },
    other: { owner: "run", latest: other, success: other } }, { editableRoute: queryConfig, onSelectTrains });
  expect(screen.getAllByRole("checkbox", { name: /选择.*G101.*张家界西到上海虹桥/ })).toHaveLength(1);
  await user.click(screen.getByRole("checkbox", { name: /选择.*G101.*张家界西到上海虹桥/ }));
  await user.click(screen.getByRole("button", { name: /将选中车次加入行程/ }));
  expect(onSelectTrains).toHaveBeenCalledWith(["G101"]);
});

test.each([
  { from_station_cn: "广州", to_station_cn: "深圳" },
  { date: "2026-10-10" },
])("changing the draft route or date clears selections even if the train code also exists there: %j", async patch => {
  const user = userEvent.setup();
  const snapshot = querySnapshot();
  const onSelectTrains = vi.fn();
  const props = { views: { first: { owner: "run", latest: snapshot, success: snapshot } }, rows: snapshot.rows,
    config: queryConfig, editableRoute: queryConfig, status: defaultStatus, now: queryTime,
    pending: false, error: null, activeQuery: null, onSelectTrains };
  const { rerender } = render(<QueryResults {...props} />);
  await user.click(screen.getByRole("checkbox", { name: /选择.*G101/ }));
  const changed = { ...queryConfig, ...patch };
  const next = querySnapshot({ conditions: { ...snapshot.conditions, from_station: changed.from_station_cn,
    to_station: changed.to_station_cn, date: changed.date } });
  rerender(<QueryResults {...props} editableRoute={changed}
    views={{ next: { owner: "manual", latest: next, success: next } }} />);
  expect(screen.queryByRole("button", { name: /将选中车次加入行程/ })).toBeNull();
  expect((screen.getByRole("checkbox", { name: /选择.*G101/ }) as HTMLInputElement).checked).toBe(false);
  expect(onSelectTrains).not.toHaveBeenCalled();
});

test("cleared results cannot apply a previously selected train", async () => {
  const user = userEvent.setup();
  const snapshot = querySnapshot();
  const onSelectTrains = vi.fn();
  const props = { config: queryConfig, editableRoute: queryConfig, status: defaultStatus, now: queryTime,
    pending: false, error: null, activeQuery: null, onSelectTrains };
  const { rerender } = render(<QueryResults {...props} rows={snapshot.rows}
    views={{ first: { owner: "run", latest: snapshot, success: snapshot } }} />);
  await user.click(screen.getByRole("checkbox", { name: /选择.*G101/ }));
  rerender(<QueryResults {...props} rows={[]} views={{}} />);
  expect(screen.queryByRole("button", { name: /将选中车次加入行程/ })).toBeNull();
  expect(onSelectTrains).not.toHaveBeenCalled();
});

const available = { status: "available", count: 3, raw: "3" } as const;
const alternate = { status: "alternate", count: null, raw: "候补" } as const;
const unavailable = { status: "unavailable", count: 0, raw: "无" } as const;
const baseRow = querySnapshot().rows[0];
const filterRows: StructuredQueryResultRow[] = [
  { ...baseRow, train: "K301", from_station: "北京西", departure_time: "23:00", arrival_time: "03:30", arrival_day_offset: 1,
    seats: { "硬座": available } },
  { ...baseRow, train: "G201", from_station: "北京南", departure_time: "07:02", arrival_time: "11:20", arrival_day_offset: 0,
    seats: { "二等座": alternate, "商务座": available } },
  { ...baseRow, train: "D301", from_station: "北京南", departure_time: "13:00", arrival_time: "15:00", arrival_day_offset: 0,
    seats: { "二等座": unavailable, "商务座": available } },
  { ...baseRow, train: "701", from_station: "北京西", departure_time: "18:00", arrival_time: "23:00", arrival_day_offset: null,
    seats: {} },
];

function viewFor(rows: StructuredQueryResultRow[], conditions = querySnapshot().conditions) {
  const result = querySnapshot({ rows, conditions });
  return { owner: "run", latest: result, success: result };
}

function displayedTrains() {
  return screen.queryAllByRole("rowheader").map(row => row.textContent);
}

test("combines train category, time, selected-seat availability and station filters, then resets the empty result", async () => {
  const user = userEvent.setup();
  show({ one: viewFor(filterRows) });
  expect(displayedTrains()).toEqual(["K301", "G201", "D301", "701"]);
  expect(screen.getByText("匹配 4 / 总计 4 趟")).toBeTruthy();
  await user.selectOptions(screen.getByLabelText("车型"), "highspeed");
  expect(displayedTrains()).toEqual(["G201", "D301"]);
  await user.selectOptions(screen.getByLabelText("发车时段"), "morning");
  expect(displayedTrains()).toEqual(["G201"]);
  await user.selectOptions(screen.getByLabelText("余票状态"), "available");
  expect(displayedTrains()).toEqual([]);
  expect(screen.getByText("匹配 0 / 总计 4 趟")).toBeTruthy();
  await user.selectOptions(screen.getByLabelText("余票状态"), "available_or_alternate");
  expect(displayedTrains()).toEqual(["G201"]);
  await user.selectOptions(screen.getByLabelText("出发站"), "北京西");
  expect(displayedTrains()).toEqual([]);
  expect(screen.getByText("匹配 0 / 总计 4 趟")).toBeTruthy();
  expect(screen.getByText("没有符合筛选条件的车次。")).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "重置筛选" }));
  expect(displayedTrains()).toEqual(["K301", "G201", "D301", "701"]);
  expect(screen.getByText("匹配 4 / 总计 4 趟")).toBeTruthy();
});

test("sorts rows by departure, arrival across midnight, and duration, and only shows calculable durations", async () => {
  const user = userEvent.setup();
  show({ one: viewFor(filterRows) });
  const overnight = screen.getByRole("row", { name: /^K301 / });
  const sameDay = screen.getByRole("row", { name: /^G201 / });
  const unknownDay = screen.getByRole("row", { name: /^701 / });
  expect(within(overnight).getByText("历时 4小时30分")).toBeTruthy();
  expect(within(sameDay).getByText("历时 4小时18分")).toBeTruthy();
  expect(within(unknownDay).getByText("到达日未知")).toBeTruthy();
  expect(within(unknownDay).queryByText(/历时/)).toBeNull();
  const sort = screen.getByLabelText("排序方式");
  await user.selectOptions(sort, "departure");
  expect(displayedTrains()).toEqual(["G201", "D301", "701", "K301"]);
  await user.selectOptions(sort, "arrival");
  expect(displayedTrains()).toEqual(["G201", "D301", "K301", "701"]);
  await user.selectOptions(sort, "duration");
  expect(displayedTrains()).toEqual(["D301", "G201", "K301", "701"]);
  await user.selectOptions(sort, "default");
  expect(displayedTrains()).toEqual(["K301", "G201", "D301", "701"]);
});

test("only lists a departure station filter when there are multiple stations", () => {
  show({ one: viewFor(filterRows.filter(row => row.from_station === "北京南")) });
  expect(screen.getByLabelText("车型")).toBeTruthy();
  expect(screen.queryByLabelText("出发站")).toBeNull();
});

test("type filtering combines calibrated prefixes with confirmed seats on T and K trains", async () => {
  const user = userEvent.setup();
  const prefixes = ["X1", "G2", "D3", "C4", "S5", "Z6", "N7", "V8", "Y9", "L10", "011"];
  const trains: StructuredQueryResultRow[] = [
    ...prefixes.map(train => ({ ...baseRow, train, seats: {} })),
    { ...baseRow, train: "T12", seats: {} },
    { ...baseRow, train: "K13", seats: { 硬座: available, 二等座: alternate } },
    { ...baseRow, train: "T14", seats: { 硬座: unavailable, 二等座: { status: "unknown", count: null, raw: "*" } } },
    { ...baseRow, train: "K15", seats: { 硬卧: alternate, 二等座: { status: "not_applicable", count: null, raw: "不适用" } } },
    { ...baseRow, train: "T16", seats: { 二等座: available } },
    { ...baseRow, train: "K17", seats: {} },
  ];
  show({ one: viewFor(trains) });
  const category = screen.getByLabelText("车型");
  await user.selectOptions(category, "highspeed");
  expect(displayedTrains()).toEqual(["X1", "G2", "D3", "C4", "S5", "T12", "K13", "T16", "K17"]);
  await user.selectOptions(category, "normal");
  expect(displayedTrains()).toEqual(["Z6", "N7", "V8", "T14", "K15"]);
  await user.selectOptions(category, "other");
  expect(displayedTrains()).toEqual(["Y9", "L10", "011"]);
});

test("a new query date clears selections and resets an unavailable departure station", async () => {
  const user = userEvent.setup();
  const onSelectTrains = vi.fn();
  const props = { config: queryConfig, status: defaultStatus, now: queryTime, pending: false, error: null, activeQuery: null, onSelectTrains };
  const { rerender } = render(<QueryResults {...props} views={{ one: viewFor(filterRows) }} rows={filterRows} editableRoute={queryConfig} />);
  await user.selectOptions(screen.getByLabelText("出发站"), "北京南");
  await user.click(screen.getByRole("button", { name: "全选当前筛选（2）" }));
  expect(screen.getByRole("button", { name: "将选中车次加入行程（2）" })).toBeTruthy();

  const date = "2026-09-23";
  const conditions = { ...querySnapshot().conditions, date };
  const nextRows = [{ ...filterRows[0], date }, { ...filterRows[1], date, from_station: "北京站" }];
  const next = { ...props, editableRoute: { ...queryConfig, date } };
  rerender(<QueryResults {...next} views={{ next: viewFor(nextRows, conditions) }} rows={nextRows} />);
  expect(screen.getByLabelText("出发站")).toHaveProperty("value", "");
  expect(displayedTrains()).toEqual(["K301", "G201"]);
  expect(screen.queryByRole("checkbox", { checked: true })).toBeNull();
  expect(screen.queryByRole("button", { name: /将选中车次加入行程/ })).toBeNull();

  const returningRows = [...nextRows, { ...filterRows[2], date }];
  rerender(<QueryResults {...next} views={{ next: viewFor(returningRows, conditions) }} rows={returningRows} />);
  expect(screen.getByLabelText("出发站")).toHaveProperty("value", "");
  expect(displayedTrains()).toEqual(["K301", "G201", "D301"]);
});

test("bulk selection deduplicates visible trains and preserves hidden choices when the visible selection is cleared", async () => {
  const user = userEvent.setup();
  const conditions = querySnapshot().conditions;
  const onSelectTrains = vi.fn();
  show({
    one: viewFor(filterRows),
    duplicate: viewFor([{ ...filterRows[1], date: "2026-09-23" }], { ...conditions, date: "2026-09-23" }),
    other: viewFor([
      { ...filterRows[1], train: "C333" },
      { ...filterRows[2], from_station: "广州南" },
    ], { ...conditions, from_station: "广州" }),
  }, { editableRoute: queryConfig, onSelectTrains });
  await user.click(screen.getByRole("checkbox", { name: /选择.*K301/ }));
  await user.selectOptions(screen.getByLabelText("车型"), "highspeed");
  expect(screen.getByText("C333")).toBeTruthy();
  expect(screen.queryByRole("checkbox", { name: /选择.*C333/ })).toBeNull();
  await user.click(screen.getByRole("button", { name: "全选当前筛选（2）" }));
  expect(screen.getAllByRole("checkbox", { checked: true })).toHaveLength(3);
  expect(screen.getByRole("button", { name: "将选中车次加入行程（3）" })).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "取消全选" }));
  expect(screen.queryByRole("checkbox", { checked: true })).toBeNull();
  await user.click(screen.getByRole("button", { name: "将选中车次加入行程（1）" }));
  expect(onSelectTrains).toHaveBeenCalledExactlyOnceWith(["K301"]);
  await user.click(screen.getByRole("button", { name: "全选当前筛选（2）" }));
  await user.click(screen.getByRole("button", { name: "将选中车次加入行程（2）" }));
  expect([...(onSelectTrains.mock.lastCall?.[0] ?? [])].sort()).toEqual(["D301", "G201"]);
  await user.selectOptions(screen.getByLabelText("出发站"), "广州南");
  expect(displayedTrains()).toEqual(["D301"]);
  expect(screen.queryByRole("checkbox")).toBeNull();
  expect(screen.queryByRole("button", { name: /全选/ })).toBeNull();
});

test("the filter toolbar is unavailable for raw fallback rows or an empty structured result", () => {
  const { unmount } = show({}, { rows: [{ train: "G1", raw: "张家界 无座 有" }] });
  expect(screen.queryByLabelText("车型")).toBeNull();
  unmount();
  show({ one: viewFor([]) });
  expect(screen.queryByLabelText("车型")).toBeNull();
  expect(screen.getByText("上次成功查询未返回车次。")).toBeTruthy();
});
