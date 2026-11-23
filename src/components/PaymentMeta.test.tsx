// @vitest-environment jsdom
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { PaymentMeta } from "./PaymentMeta";

afterEach(() => { cleanup(); vi.useRealTimers(); });

test("counts down in real time, shows urgency below five minutes, and leaves order status to the official site", () => {
  vi.useFakeTimers();
  const now = new Date("2026-11-22T09:00:00+08:00");
  vi.setSystemTime(now);
  render(<PaymentMeta pendingPayment review={{ payment_deadline_at: now.getTime() / 1000 + 300 }} />);
  const timer = screen.getByRole("timer");
  expect(timer.textContent).toBe("05:00");
  expect(timer.closest("dd")?.classList.contains("is-urgent")).toBe(false);
  act(() => vi.advanceTimersByTime(1000));
  expect(timer.textContent).toBe("04:59");
  expect(timer.closest("dd")?.classList.contains("is-urgent")).toBe(true);
  act(() => vi.advanceTimersByTime(299_000));
  expect(screen.queryByRole("timer")).toBeNull();
  expect(screen.getByText("倒计时已到，请核对官方状态")).toBeTruthy();
});

test("shows official price and seats for a finished order without reviving its countdown", () => {
  render(<PaymentMeta review={{ payment_deadline_at: Date.now() / 1000 + 30,
    ticket_price: "661.0", seat_assignments: ["09车02A号", "09车02B号"] }} />);
  expect(screen.getByText("¥661.0")).toBeTruthy();
  expect(screen.getAllByRole("listitem").map(item => item.textContent)).toEqual(["09车02A号", "09车02B号"]);
  expect(screen.queryByText("支付倒计时")).toBeNull();
});

test("leaves absent or invalid payment metadata blank", () => {
  const { container, rerender } = render(<PaymentMeta />);
  expect(container.childElementCount).toBe(0);
  rerender(<PaymentMeta pendingPayment review={{ payment_deadline_at: NaN, ticket_price: "unknown", seat_assignments: [] }} />);
  expect(container.childElementCount).toBe(0);
});
