// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { AlternateSettings } from "./AlternateSettings";
import { AlternateReview } from "./AlternateReview";
import { defaultConfig } from "../store/railwatchStore";
import type { RailWatchConfig } from "../types";
import type { CommandRunner } from "./componentTypes";

afterEach(cleanup);

test("sleeper waitlist explains official berth allocation without offering an unsupported berth preference", () => {
  const props = { update: vi.fn(), disabled: false, runCommand: vi.fn(async () => undefined) };
  const config = { ...defaultConfig, auto_alternate: true, seat_keyword: "硬卧，软卧" };
  const view = render(<AlternateSettings {...props} config={config} />);
  expect(screen.getByText(/卧铺候补的上／中／下铺由官网分配/)).toBeTruthy();
  expect(screen.queryByRole("combobox", { name: "铺位" })).toBeNull();
  view.rerender(<AlternateSettings {...props} config={{ ...config, seat_keyword: "一等座" }} />);
  expect(screen.queryByText(/卧铺候补的上／中／下铺由官网分配/)).toBeNull();
});

test("new-train conditions start off and explicit date/hour choices persist without changing route or seat", async () => {
  const user = userEvent.setup();
  let saved: RailWatchConfig = { ...defaultConfig, date: "2026-10-10", date_range: "单日", auto_alternate: true, seat_keyword: "二等座" };
  const runCommand = vi.fn(async (_command: string) => undefined);
  function Form() {
    const [config, setConfig] = useState(saved);
    return <AlternateSettings config={config} update={patch => { saved = { ...config, ...patch }; setConfig(saved); }}
      runCommand={runCommand} disabled={false} />;
  }
  render(<Form />);
  expect(screen.queryByRole("button", { name: "添加新增列车日期" })).toBeNull();
  await user.click(screen.getByRole("switch", { name: "接受新增列车" }));
  await user.click(screen.getByRole("button", { name: "添加新增列车日期" }));
  await user.click(screen.getByRole("combobox", { name: "最早出发 1" }));
  await user.click(await screen.findByText("8点", { selector: ".ant-select-item-option-content" }));
  expect(saved.alternate_new_train_windows).toEqual([{ date: "2026-10-10", start_hour: 8, end_hour: 24 }]);
  await user.click(screen.getByRole("switch", { name: "接受新增列车" }));
  expect(saved.alternate_accept_new_trains).toBe(false);
  expect(saved.alternate_new_train_windows).toHaveLength(1);
  expect(saved.seat_keyword).toBe("二等座");
  expect(saved.from_station_cn).toBe("北京");
  expect(runCommand.mock.calls.map(call => call[0])).not.toContain("continueOrder");
});

test("options from a different route cannot be selected as this trip's official options", async () => {
  render(<AlternateSettings config={{ ...defaultConfig, date: "2026-10-10", auto_alternate: true }}
    update={vi.fn()} disabled={false} runCommand={(async () => ({ snapshot: { from_station: "广州", to_station: "深圳",
      dates: ["2026-10-10"], observed_at: 1, deadline_options: ["开车前3天"] }, warning: null })) as CommandRunner} />);
  expect(await screen.findByText(/路线或日期已变更/)).toBeTruthy();
  await userEvent.click(screen.getByRole("combobox", { name: "截止兑现时间" }));
  expect(screen.queryByText("开车前3天")).toBeNull();
});

test("a city-level trip finds options read for it from its actual station and syncs with its own route", async () => {
  const user = userEvent.setup();
  const update = vi.fn();
  const runCommand = vi.fn(async (_command: string, payload?: Record<string, unknown>) => ({ snapshot: {
    from_station: "北京南", to_station: "上海虹桥", trip_from_station: "北京", trip_to_station: "上海",
    dates: ["2026-10-10"], observed_at: 1, deadline_options: ["开车前20分钟", "开车前1小时"] },
    warning: payload?.refresh ? null : null }));
  render(<AlternateSettings config={{ ...defaultConfig, date: "2026-10-10", auto_alternate: true }}
    update={update} disabled={false} runCommand={runCommand as CommandRunner} />);
  expect(await screen.findByText(/已同步/)).toBeTruthy();
  await user.click(screen.getByRole("combobox", { name: "截止兑现时间" }));
  await user.click(await screen.findByText("开车前20分钟", { selector: ".ant-select-item-option-content" }));
  expect(update).toHaveBeenCalledWith({ alternate_deadline: "开车前20分钟" });
  await user.click(screen.getByRole("button", { name: "同步官网截止选项" }));
  expect(runCommand).toHaveBeenLastCalledWith("readAlternateOptions",
    { refresh: true, from_station: "北京", to_station: "上海" });
});

test("an unsupported legacy deadline offers the default before any official options are read", async () => {
  const user = userEvent.setup();
  const update = vi.fn();
  render(<AlternateSettings config={{ ...defaultConfig, date: "2026-10-10", auto_alternate: true,
    alternate_deadline: "2026-10-01 18:00" }} update={update} disabled={false}
    runCommand={(async () => ({ snapshot: null, warning: null })) as CommandRunner} />);
  expect(await screen.findByText(/请重新选择截止兑现时间/)).toBeTruthy();
  await user.click(screen.getByRole("combobox", { name: "截止兑现时间" }));
  await user.click(await screen.findByText("开车前1小时（提交前核对官网选项）", { selector: ".ant-select-item-option-content" }));
  expect(update).toHaveBeenCalledWith({ alternate_deadline: "开车前1小时" });
});

test("official rate handles zero, stale timestamps and missing values without implying a guarantee", () => {
  const view = render(<AlternateReview deadline="开车前60分钟" review={{ success_rate: 0, success_rate_status: "available",
    success_rate_observed_at: Date.now() / 1000, prepay_amount: "661.00", amount_observed_at: Date.now() / 1000 }} />);
  const fact = (label: string) => screen.getByText(label, { selector: "dt" }).nextElementSibling?.textContent;
  expect(fact("预估成功率")).toBe("0%");
  expect(fact("预付款")).toBe("661.00 元");
  expect(fact("截止兑现")).toBe("开车前1小时");
  view.rerender(<AlternateReview review={{ success_rate: 40, success_rate_status: "available", success_rate_observed_at: 1 }} />);
  expect(fact("预估成功率")).toMatch(/^40%（已失效/);
  view.rerender(<AlternateReview />);
  expect(fact("预估成功率")).toBe("官网暂未提供");
});
