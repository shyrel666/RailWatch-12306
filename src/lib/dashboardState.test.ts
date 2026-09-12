import { expect, test } from "vitest";
import { defaultStatus } from "../store/railwatchStore";
import { dashboardAction, hasUnresolvedOrder } from "./dashboardState";

test.each([
  "pending_payment",
  "alternate_pending_payment",
  "verification",
  "unknown",
])("prioritizes %s order over running task", (status) => {
  expect(
    dashboardAction(
      { ...defaultStatus, monitoring: true, order: { status } },
      null,
      true,
    ).section,
  ).toBe("monitor-attention");
});
test("does not treat confirmed no-order or completed orders as unresolved", () => {
  for (const status of ["not_submitted", "sold_out"]) {
    expect(hasUnresolvedOrder({ status, no_order: true })).toBe(false);
    expect(hasUnresolvedOrder({ status, no_order: false })).toBe(true);
  }
  expect(hasUnresolvedOrder({ status: "fulfilled" })).toBe(false);
  expect(
    hasUnresolvedOrder({ status: "fulfilled", recovery_required: true }),
  ).toBe(true);
});
test("routes login to settings and incomplete trip to trip setup", () => {
  expect(
    dashboardAction({ ...defaultStatus, environment_ready: true }, null, false)
      .section,
  ).toBe("settings-login");
  expect(
    dashboardAction(
      {
        ...defaultStatus,
        environment_ready: true,
        login_ready: true,
        query_ready: true,
      },
      null,
      false,
    ).section,
  ).toBe("trip-basics");
});
