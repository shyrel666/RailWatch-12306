// @vitest-environment jsdom
import { act, cleanup, render, screen, fireEvent } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { VirtualEventList } from "./VirtualEventList";
import { MonitorPage } from "./MonitorPage";
import { defaultConfig, defaultStatus, railwatchStore } from "../store/railwatchStore";
import { useBeijingToday, todayIso } from "../lib/tripDate";
afterEach(() => { cleanup(); vi.useRealTimers(); });

test("virtual feed renders a bounded slice and can reach its last entry", () => {
  const entries = Array.from({length:1000}, (_, id) => ({id, time:"12:00:00", level:"INFO", message:`event-${id}`, title:`event-${id}`, detail:null, tone:"info" as const, label:"信息"}));
  render(<VirtualEventList entries={entries} className="event-list" />);
  expect(screen.getAllByRole("article").length).toBeLessThan(25);
  fireEvent.scroll(screen.getByRole("feed"), {target:{scrollTop:88*995}});
  expect(screen.getByText("event-999")).toBeTruthy();
});

test("running view uses the task snapshot and backend deadline", () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-09-06T08:00:00+08:00"));
  const current = {...defaultConfig, from_station_cn:"北京", to_station_cn:"上海", date:"2026-09-06"};
  railwatchStore.setState({config:{...current, from_station_cn:"广州"}, status:{...defaultStatus, monitoring:true, current_config:current, task:{run_id:"test",status:"backoff",started_at:Date.now()/1000-65,next_query_at:Date.now()/1000+7}}, results:[],hits:[],lastHumanAction:null});
  render(<MonitorPage busy={null} runCommand={vi.fn()} />);
  expect(screen.getByText("北京 → 上海")).toBeTruthy();
  expect(screen.queryByText("广州 → 上海")).toBeNull();
  expect(screen.getByText("00:01:05")).toBeTruthy();
  expect(screen.getByText("7s")).toBeTruthy();
  act(() => vi.advanceTimersByTime(2000));
  expect(screen.getByText("下次刷新").parentElement?.textContent).toContain("5s");
});

test("date hint refreshes at Beijing midnight and window focus", () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-09-06T15:59:59Z"));
  function DateProbe() { return <span>{todayIso(useBeijingToday())}</span>; }
  render(<DateProbe />);
  expect(screen.getByText("2026-09-06")).toBeTruthy();
  act(() => vi.advanceTimersByTime(1100));
  expect(screen.getByText("2026-09-07")).toBeTruthy();
  vi.setSystemTime(new Date("2026-09-08T16:00:00Z"));
  fireEvent.focus(window);
  expect(screen.getByText("2026-09-09")).toBeTruthy();
});
