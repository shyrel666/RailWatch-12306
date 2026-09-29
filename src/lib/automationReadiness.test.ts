import { expect, test } from "vitest";
import { defaultConfig } from "../store/railwatchStore";
import type { RailWatchConfig } from "../types";
import { automationConfigIssue } from "./automationReadiness";
import shared from "../../tests/fixtures/automation-readiness-cases.json";

const sharedBase = { ...defaultConfig, ...shared.base } as RailWatchConfig;

test.each(shared.valid.map(patch => [patch]))("accepts shared valid case %j like the bridge", patch => {
  expect(automationConfigIssue({ ...sharedBase, ...patch } as RailWatchConfig, shared.capabilities)).toBeNull();
});

test.each(shared.invalid.map(({ patch, expected }) => [patch, expected] as const))(
  "reports the same first issue as the bridge for %j", (patch, expected) => {
    expect(automationConfigIssue({ ...sharedBase, ...patch } as RailWatchConfig, shared.capabilities)).toContain(expected);
  });

const config = { ...defaultConfig, auto_submit: true, train_code: "G9", passengers: "测试甲，测试乙", seat_keyword: "二等座" };
const capabilities = [
  { name: "二等座", query: true, regular: true, alternate: true },
  { name: "一等座", query: true, regular: true, alternate: false },
  { name: "商务座", query: true, regular: false, alternate: false },
];

test("accepts supported automation and leaves unrestricted monitoring available", () => {
  expect(automationConfigIssue(config, capabilities)).toBeNull();
  expect(automationConfigIssue({ ...defaultConfig, auto_submit: false, auto_alternate: false })).toBeNull();
});

test.each([
  [{ train_code: " " }, "目标车次"],
  [{ passengers: "" }, "添加乘客"],
  [{ passengers: "测试甲、测试甲" }, "姓名重复"],
  [{ seat_keyword: "" }, "不能使用“不限”"],
  [{ auto_submit: false, auto_alternate: true, seat_keyword: "" }, "不能使用“不限”"],
  [{ seat_keyword: "商务座" }, "不支持"],
  [{ auto_alternate: true, seat_keyword: "一等座" }, "不支持"],
  [{ passenger_selections: [{ name: "测试甲", ticket_type: "student" as const, identity_hint: "" }] }, "成人"],
])("identifies invalid automation settings %j", (patch, expected) => {
  expect(automationConfigIssue({ ...config, ...patch }, capabilities)).toContain(expected);
});
