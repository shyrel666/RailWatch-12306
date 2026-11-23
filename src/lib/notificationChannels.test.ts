import { expect, expectTypeOf, test } from "vitest";
import type { NotificationSettings, NotificationSettingsPatch } from "../types";
import {
  NOTIFICATION_CHANNELS, NOTIFICATION_REQUIRED_FIELDS, NOTIFICATION_SECRET_FIELDS, notificationFieldLabel,
  type NotificationChannelField, type NotificationChannelId, type NotificationSecretField,
  type NotificationSwitchField, type NotificationTextField,
} from "./notificationChannels";

test("the shared table lists channels in order and marks their secrets", () => {
  expect(NOTIFICATION_CHANNELS).toEqual([
    { id: "server_chan", label: "Server酱" }, { id: "email", label: "邮件" }, { id: "wecom_webhook", label: "企业微信" },
    { id: "bark", label: "Bark" }, { id: "ntfy", label: "ntfy" }, { id: "dingtalk", label: "钉钉机器人" },
    { id: "feishu", label: "飞书机器人" }, { id: "pushplus", label: "PushPlus" }, { id: "custom_webhook", label: "自定义 Webhook" },
  ]);
  expect(NOTIFICATION_SECRET_FIELDS).toEqual(["server_chan_key", "email_password", "wecom_webhook_url",
    "bark_key", "ntfy_topic_url", "ntfy_token", "dingtalk_webhook_url", "dingtalk_secret", "feishu_webhook_url",
    "feishu_secret", "pushplus_token", "custom_webhook_url", "custom_webhook_token"]);
  expect(NOTIFICATION_REQUIRED_FIELDS).toMatchObject({ dingtalk: ["dingtalk_webhook_url"], feishu: ["feishu_webhook_url"],
    pushplus: ["pushplus_token"], custom_webhook: ["custom_webhook_url"] });
  expect(notificationFieldLabel("email_smtp_port")).toBe("SMTP 端口");
});

test("settings types are derived from the table", () => {
  // Checked by `npm run typecheck`: a table edit changes these unions, not hand-written copies.
  expectTypeOf<NotificationChannelId>().toEqualTypeOf<"server_chan" | "email" | "wecom_webhook" | "bark" | "ntfy" |
    "dingtalk" | "feishu" | "pushplus" | "custom_webhook">();
  expectTypeOf<NotificationSecretField>().toEqualTypeOf<"server_chan_key" | "email_password" | "wecom_webhook_url" |
    "bark_key" | "ntfy_topic_url" | "ntfy_token" | "dingtalk_webhook_url" | "dingtalk_secret" | "feishu_webhook_url" |
    "feishu_secret" | "pushplus_token" | "custom_webhook_url" | "custom_webhook_token">();
  expectTypeOf<NotificationSwitchField>().toEqualTypeOf<"bark_critical" | "bark_call">();
  expectTypeOf<NotificationTextField>().toEqualTypeOf<"email_smtp_host" | "email_user" | "email_to" | "bark_server" | "pushplus_channel">();
  expectTypeOf<NotificationChannelField>().toEqualTypeOf<NotificationSecretField | NotificationSwitchField |
    NotificationTextField | "email_smtp_port">();
  expectTypeOf<NotificationSettings["email_smtp_port"]>().toEqualTypeOf<number>();
  expectTypeOf<NotificationSettings["bark_critical"]>().toEqualTypeOf<boolean>();
  expectTypeOf<NotificationSettings["ntfy_enabled"]>().toEqualTypeOf<boolean>();
  expectTypeOf<NotificationSettings["ntfy_token_configured"]>().toEqualTypeOf<boolean | undefined>();
  expectTypeOf<NotificationSettings["custom_webhook_url_configured"]>().toEqualTypeOf<boolean | undefined>();
  expectTypeOf<NotificationSettingsPatch["feishu_secret"]>().toEqualTypeOf<string | null | undefined>();
  expectTypeOf<NotificationSettingsPatch["bark_key"]>().toEqualTypeOf<string | null | undefined>();
  expectTypeOf<NotificationSettingsPatch>().not.toHaveProperty("bark_key_configured");
  expectTypeOf<NotificationSettingsPatch>().not.toHaveProperty("event_channels_seeded");
});
