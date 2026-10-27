import { expect, expectTypeOf, test } from "vitest";
import type { NotificationSettings, NotificationSettingsPatch } from "../types";
import {
  NOTIFICATION_CHANNELS, NOTIFICATION_SECRET_FIELDS, notificationFieldLabel,
  type NotificationChannelField, type NotificationChannelId, type NotificationSecretField,
  type NotificationSwitchField, type NotificationTextField,
} from "./notificationChannels";

test("the shared table lists channels in order and marks their secrets", () => {
  expect(NOTIFICATION_CHANNELS).toEqual([
    { id: "server_chan", label: "Server酱" }, { id: "email", label: "邮件" }, { id: "wecom_webhook", label: "企业微信" },
    { id: "bark", label: "Bark" }, { id: "ntfy", label: "ntfy" },
  ]);
  expect(NOTIFICATION_SECRET_FIELDS).toEqual(["server_chan_key", "email_password", "wecom_webhook_url",
    "bark_key", "ntfy_topic_url", "ntfy_token"]);
  expect(notificationFieldLabel("email_smtp_port")).toBe("SMTP 端口");
});

test("settings types are derived from the table", () => {
  // Checked by `npm run typecheck`: a table edit changes these unions, not hand-written copies.
  expectTypeOf<NotificationChannelId>().toEqualTypeOf<"server_chan" | "email" | "wecom_webhook" | "bark" | "ntfy">();
  expectTypeOf<NotificationSecretField>().toEqualTypeOf<"server_chan_key" | "email_password" | "wecom_webhook_url" |
    "bark_key" | "ntfy_topic_url" | "ntfy_token">();
  expectTypeOf<NotificationSwitchField>().toEqualTypeOf<"bark_critical" | "bark_call">();
  expectTypeOf<NotificationTextField>().toEqualTypeOf<"email_smtp_host" | "email_user" | "email_to" | "bark_server">();
  expectTypeOf<NotificationChannelField>().toEqualTypeOf<NotificationSecretField | NotificationSwitchField |
    NotificationTextField | "email_smtp_port">();
  expectTypeOf<NotificationSettings["email_smtp_port"]>().toEqualTypeOf<number>();
  expectTypeOf<NotificationSettings["bark_critical"]>().toEqualTypeOf<boolean>();
  expectTypeOf<NotificationSettings["ntfy_enabled"]>().toEqualTypeOf<boolean>();
  expectTypeOf<NotificationSettings["ntfy_token_configured"]>().toEqualTypeOf<boolean | undefined>();
  expectTypeOf<NotificationSettingsPatch["bark_key"]>().toEqualTypeOf<string | null | undefined>();
  expectTypeOf<NotificationSettingsPatch>().not.toHaveProperty("bark_key_configured");
  expectTypeOf<NotificationSettingsPatch>().not.toHaveProperty("event_channels_seeded");
});
