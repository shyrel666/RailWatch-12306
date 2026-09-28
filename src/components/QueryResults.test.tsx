// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { QueryResults } from "./QueryResults";
import { defaultStatus } from "../store/railwatchStore";
import { queryConfig, querySnapshot, queryTime } from "../test/queryFixtures";
import { queryRows, type QueryViews } from "../lib/queryResults";

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
