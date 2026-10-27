// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
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

test("channel forms fold away until a channel is switched on, and events list only enabled channels", async () => {
  const command = mockSoundPreferences();
  render(<NotificationSettingsPanel />);
  const expand = await screen.findByRole("button", { name: "Bark设置" });
  expect(expand.getAttribute("aria-expanded")).toBe("false");
  expect(screen.queryByRole("switch", { name: "静音也响" })).toBeNull();
  expect(screen.queryByRole("checkbox", { name: /·/ })).toBeNull();
  expect(screen.getByText("开启外部渠道后，在这里选择各渠道推送哪些事件。")).toBeTruthy();

  await userEvent.click(screen.getByRole("switch", { name: "Bark" }));
  expect(expand.getAttribute("aria-expanded")).toBe("true");
  expect(screen.getByText("已开启，还有必填项未填写")).toBeTruthy();
  await userEvent.type(screen.getByLabelText("Bark 设备 Key"), "device-key");
  expect(screen.queryByText("已开启，还有必填项未填写")).toBeNull();
  expect(expand.getAttribute("aria-expanded")).toBe("true");
  await userEvent.click(screen.getByRole("switch", { name: "静音也响" }));
  expect(screen.getAllByRole("row")).toHaveLength(2);
  await userEvent.click(screen.getByRole("checkbox", { name: "待支付 · Bark" }));
  expect(screen.queryByRole("checkbox", { name: "待支付 · ntfy" })).toBeNull();

  await userEvent.click(screen.getByRole("button", { name: "ntfy设置" }));
  expect(screen.getByLabelText("ntfy 主题地址").getAttribute("placeholder")).toBe("https://ntfy.sh/你的主题名");
  await userEvent.click(screen.getByRole("button", { name: "保存通知设置" }));
  await waitFor(() => expect(command).toHaveBeenCalledWith("savePreferences", { notification_settings: expect.objectContaining({
    bark_enabled: true, bark_key: "device-key", bark_critical: true,
  }) }));
  const saved = command.mock.calls.find(([name]) => name === "savePreferences")![1] as { notification_settings: { event_channels: Record<string, string[]> } };
  expect(saved.notification_settings.event_channels.payment).toEqual(["bark"]);
});

test("a configured channel loads folded and one missing its key loads open", async () => {
  vi.spyOn(railwatchApi, "command").mockImplementation(async (name) => {
    if (name === "loadPreferences") return { notification_settings: {
      desktop_urgent: true, sound_loop: true, window_attention: true,
      server_chan_enabled: true, server_chan_key: "", server_chan_key_configured: true,
      ntfy_enabled: true, ntfy_topic_url: "", ntfy_topic_url_configured: false,
      event_channels: { hit: ["server_chan", "ntfy"] },
    } } as never;
    return {} as never;
  });
  render(<NotificationSettingsPanel />);
  expect((await screen.findByRole("button", { name: "Server酱设置" })).getAttribute("aria-expanded")).toBe("false");
  expect(screen.getByRole("button", { name: "ntfy设置" }).getAttribute("aria-expanded")).toBe("true");
  expect(screen.getByRole("checkbox", { name: "发现余票 · Server酱" })).toHaveProperty("checked", true);
  expect(screen.getByRole("checkbox", { name: "待支付 · ntfy" })).toHaveProperty("checked", false);
});

function mockSoundPreferences() {
  let settings: Record<string, unknown> = {
    desktop_urgent: true, sound_loop: true, window_attention: true,
    sound_tone: "beep", sound_custom_file: "", sound_custom_name: "",
    event_channels: Object.fromEntries(["hit", "verification", "payment", "alternate_active", "alternate_fulfilled", "purchase_success"]
      .map((event) => [event, []])),
  };
  return vi.spyOn(railwatchApi, "command").mockImplementation(async (name, payload = {}) => {
    if (name === "savePreferences") settings = { ...settings, ...(payload.notification_settings as Record<string, unknown>) };
    if (name === "loadPreferences" || name === "savePreferences") return { notification_settings: settings } as never;
    return {} as never;
  });
}

test("previews an unsaved preset once, stops on demand, and saves through the existing preferences command", async () => {
  const command = mockSoundPreferences();
  const preview = vi.spyOn(railwatchApi, "previewAlertSound").mockResolvedValue({ duration_ms: 5000 });
  const stop = vi.spyOn(railwatchApi, "stopAlertSoundPreview").mockImplementation(() => undefined);
  render(<NotificationSettingsPanel />);
  const select = await screen.findByRole("combobox", { name: "提示音" });
  expect(screen.getByText("经典哔声")).toBeTruthy();
  await userEvent.click(select);
  expect(screen.getAllByRole("option")).toHaveLength(5);
  expect(screen.getByRole("option", { name: /经典哔声/ }).getAttribute("aria-selected")).toBe("true");
  await userEvent.click(screen.getByRole("option", { name: /清脆双响/ }));
  await userEvent.click(screen.getByRole("button", { name: "试听" }));
  expect(preview).toHaveBeenCalledWith({ sound_tone: "double", sound_custom_file: "" });
  expect(command).not.toHaveBeenCalledWith("testNotification");
  expect(command.mock.calls.some(([name]) => name === "savePreferences")).toBe(false);
  await userEvent.click(screen.getByRole("button", { name: "停止试听" }));
  expect(stop).toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "保存通知设置" }));
  await waitFor(() => expect(command).toHaveBeenCalledWith("savePreferences", { notification_settings: { sound_tone: "double" } }));
});

test("a cancelled import keeps the form intact and a selected file is saved with its friendly name", async () => {
  const command = mockSoundPreferences();
  const asset = { file: "a".repeat(64) + ".wav", name: "我的提示音.wav" };
  vi.spyOn(railwatchApi, "importAlertSound").mockResolvedValueOnce(null).mockResolvedValueOnce(asset);
  render(<NotificationSettingsPanel />);
  await userEvent.click(await screen.findByRole("combobox", { name: "提示音" }));
  await userEvent.click(screen.getByRole("option", { name: /自定义音频/ }));
  expect((screen.getByRole("button", { name: "试听" }) as HTMLButtonElement).disabled).toBe(true);
  await userEvent.click(screen.getByRole("button", { name: "保存通知设置" }));
  expect(screen.getByRole("alert").textContent).toContain("先选择自定义音频");
  await userEvent.click(screen.getByRole("button", { name: "选择音频" }));
  expect(screen.getByText("未选择音频")).toBeTruthy();
  // The cancelled import settles asynchronously; wait for its loading state to clear.
  await userEvent.click(await screen.findByRole("button", { name: "选择音频" }));
  expect(await screen.findByText(asset.name)).toBeTruthy();
  expect((screen.getByRole("button", { name: "试听" }) as HTMLButtonElement).disabled).toBe(false);
  await userEvent.click(screen.getByRole("button", { name: "保存通知设置" }));
  await waitFor(() => expect(command).toHaveBeenCalledWith("savePreferences", {
    notification_settings: { sound_tone: "custom", sound_custom_file: asset.file, sound_custom_name: asset.name },
  }));
});

test("an audio import failure is shown without altering saved settings", async () => {
  const command = mockSoundPreferences();
  vi.spyOn(railwatchApi, "importAlertSound").mockRejectedValue(new Error("自定义提示音长度须在 15 秒以内。"));
  render(<NotificationSettingsPanel />);
  await userEvent.click(await screen.findByRole("combobox", { name: "提示音" }));
  await userEvent.click(screen.getByRole("option", { name: /自定义音频/ }));
  await userEvent.click(screen.getByRole("button", { name: "选择音频" }));
  expect((await screen.findByRole("alert")).textContent).toContain("15 秒以内");
  expect(screen.getByText("未选择音频")).toBeTruthy();
  expect(command.mock.calls.some(([name]) => name === "savePreferences")).toBe(false);
});

test("stopping an in-flight preview ignores a late response and unmounting releases preview audio", async () => {
  mockSoundPreferences();
  let complete!: (value: { duration_ms: number }) => void;
  vi.spyOn(railwatchApi, "previewAlertSound").mockImplementation(() => new Promise((resolve) => { complete = resolve; }));
  const stop = vi.spyOn(railwatchApi, "stopAlertSoundPreview").mockImplementation(() => undefined);
  const view = render(<NotificationSettingsPanel />);
  await userEvent.click(await screen.findByRole("button", { name: "试听" }));
  await userEvent.click(screen.getByRole("button", { name: "停止试听" }));
  await act(async () => complete({ duration_ms: 15000 }));
  expect(screen.getByRole("button", { name: "试听" })).toBeTruthy();
  const calls = stop.mock.calls.length;
  view.unmount();
  expect(stop).toHaveBeenCalledTimes(calls + 1);
});
