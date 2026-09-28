// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { railwatchApi } from "../lib/railwatchApi";
import { NotificationSettingsPanel } from "./NotificationSettingsPanel";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

test.each(["success", "queued"])("requires saving edits and reports %s delivery without exposing secrets", async (deliveryStatus) => {
  const settings = {
    desktop_urgent: true, sound_loop: true, window_attention: true,
    server_chan_enabled: true, server_chan_key: "", server_chan_key_configured: true,
    email_enabled: false, email_smtp_host: "", email_smtp_port: 465, email_user: "", email_password: "", email_to: "",
    wecom_webhook_enabled: false, wecom_webhook_url: "",
    event_channels: Object.fromEntries(["hit", "verification", "payment", "alternate_active", "alternate_fulfilled", "purchase_success"].map((event) => [event, ["server_chan", "email", "wecom_webhook"]])),
  };
  const command = vi.spyOn(railwatchApi, "command").mockImplementation(async (name, payload = {}) => {
    if (name === "loadPreferences") return { theme: "dark", close_to_tray: false, notification_settings: settings } as never;
    if (name === "savePreferences") return { theme: "dark", close_to_tray: false, notification_settings: { ...settings, ...(payload.notification_settings as Record<string, unknown>) } } as never;
    if (name === "notificationStatus") return {} as never;
    if (name === "testNotification") return { server_chan: { status: deliveryStatus, sent_at: deliveryStatus === "success" ? 100 : null } } as never;
    return {} as never;
  });
  render(<NotificationSettingsPanel />);
  const sound = await screen.findByRole("switch", { name: "循环声音" });
  expect(screen.getByText(/已配置；留空保持不变/)).toBeTruthy();
  await userEvent.click(sound);
  await userEvent.click(screen.getByRole("button", { name: "发送测试通知" }));
  expect(screen.getByRole("alert").textContent).toContain("请先保存");
  expect(command).not.toHaveBeenCalledWith("testNotification");
  await userEvent.click(screen.getByRole("button", { name: "保存通知设置" }));
  await waitFor(() => expect(command).toHaveBeenCalledWith("savePreferences", { notification_settings: { sound_loop: false } }));
  await userEvent.click(screen.getByRole("button", { name: "发送测试通知" }));
  await waitFor(() => expect(command).toHaveBeenCalledWith("testNotification"));
  if (deliveryStatus === "success") {
    expect(screen.getByText(/^成功 ·/)).toBeTruthy();
    expect(screen.getByText("测试已完成；各渠道结果见下方。")).toBeTruthy();
  } else {
    expect(screen.getByText("已排队")).toBeTruthy();
    expect(screen.getByText("部分测试通知仍在排队或发送，结果会继续更新。")).toBeTruthy();
    expect(screen.queryByText("测试已完成；各渠道结果见下方。")).toBeNull();
  }
});
