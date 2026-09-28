import { Button, Input, InputNumber, Switch } from "antd";
import { useEffect, useState } from "react";
import { railwatchApi } from "../lib/railwatchApi";
import type { NotificationSettings, NotificationSettingsPatch, RailWatchPreferences } from "../types";

type Channel = "server_chan" | "email" | "wecom_webhook";
type EventName = keyof NotificationSettings["event_channels"];
type Delivery = { status: string; sent_at: number | null };
const channels: { id: Channel; label: string }[] = [
  { id: "server_chan", label: "Server酱" }, { id: "email", label: "邮件" }, { id: "wecom_webhook", label: "企业微信" },
];
const events: { id: EventName; label: string }[] = [
  { id: "hit", label: "发现余票" }, { id: "verification", label: "需要核验" },
  { id: "payment", label: "待支付" }, { id: "alternate_active", label: "候补生效" },
  { id: "alternate_fulfilled", label: "候补兑现" },
  { id: "purchase_success", label: "购票成功" },
];
const secretFields = ["server_chan_key", "email_password", "wecom_webhook_url"] as const;
type SecretField = (typeof secretFields)[number];
const statusLabels: Record<string, string> = {
  success: "成功", failed: "失败", disabled: "已禁用", not_configured: "未配置", queued: "已排队",
  queue_full: "队列已满", duplicate: "重复事件已跳过",
};

export function NotificationSettingsPanel() {
  const [settings, setSettings] = useState<NotificationSettings | null>(null);
  const [patch, setPatch] = useState<NotificationSettingsPatch>({});
  const [status, setStatus] = useState<Record<string, Delivery>>({});
  const [working, setWorking] = useState<"save" | "test" | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => {
    let alive = true;
    void Promise.all([
      railwatchApi.command<RailWatchPreferences>("loadPreferences"),
      railwatchApi.command<Record<string, Delivery>>("notificationStatus"),
    ]).then(([preferences, delivery]) => {
      if (alive) { setSettings(preferences.notification_settings); setStatus(delivery); }
    }).catch((cause) => { if (alive) setError(cause instanceof Error ? cause.message : "通知设置加载失败。"); });
    return () => { alive = false; };
  }, []);
  useEffect(() => {
    if (!settings) return undefined;
    const timer = window.setInterval(() => {
      void railwatchApi.command<Record<string, Delivery>>("notificationStatus").then(setStatus).catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [settings]);

  const value = <K extends keyof NotificationSettings>(field: K): NotificationSettings[K] | undefined =>
    (field in patch ? patch[field as keyof NotificationSettingsPatch] : settings?.[field]) as NotificationSettings[K] | undefined;
  const change = <K extends keyof NotificationSettingsPatch>(field: K, next: NotificationSettingsPatch[K]) => {
    setPatch((current) => ({ ...current, [field]: next })); setError(""); setNotice("");
  };
  const save = async () => {
    if (!settings || Object.keys(patch).length === 0) return;
    setWorking("save"); setError("");
    try {
      const result = await railwatchApi.command<RailWatchPreferences>("savePreferences", { notification_settings: patch });
      setSettings(result.notification_settings); setPatch({}); setNotice("通知设置已保存。");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "通知设置保存失败。"); }
    finally { setWorking(null); }
  };
  const test = async () => {
    if (Object.keys(patch).length) { setError("请先保存修改，再发送测试通知。"); return; }
    setWorking("test"); setError("");
    try {
      const delivery = await railwatchApi.command<Record<string, Delivery>>("testNotification");
      setStatus(delivery);
      setNotice(Object.values(delivery).some(item => item.status === "queued")
        ? "部分测试通知仍在排队或发送，结果会继续更新。" : "测试已完成；各渠道结果见下方。");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "测试通知失败。"); }
    finally { setWorking(null); }
  };
  const secret = (field: SecretField, label: string) => {
    const edited = patch[field];
    const configured = settings?.[`${field}_configured` as keyof NotificationSettings] === true;
    return <div className="setting-row" key={field}>
      <div><strong>{label}</strong><p>{edited === null ? "保存后删除" : typeof edited === "string" && edited ? "保存后替换" : configured ? "已配置；留空保持不变" : "未配置"}</p></div>
      <div className="button-row">
        <Input.Password aria-label={label} value={typeof edited === "string" ? edited : ""} placeholder={configured ? "留空保持原值" : "输入密钥"}
          onChange={(event) => change(field, event.target.value)} style={{ width: 230 }} />
        <Button disabled={!configured && !edited} onClick={() => change(field, null)}>删除</Button>
      </div>
    </div>;
  };
  const toggle = (field: keyof NotificationSettingsPatch, label: string, detail: string) => <div className="setting-row" key={field}>
    <div><strong>{label}</strong><p>{detail}</p></div>
    <Switch aria-label={label} checked={value(field as keyof NotificationSettings) === true} onChange={(next) => change(field, next)} />
  </div>;
  if (!settings) return <section className="settings-section" id="settings-notifications"><h2>通知</h2><p>{error || "正在加载通知设置…"}</p></section>;
  const selectedEvents = value("event_channels") || settings.event_channels || Object.fromEntries(events.map(({ id }) => [id, channels.map(({ id: channel }) => channel)])) as NotificationSettings["event_channels"];
  const deliveryLabel = (channel: Channel) => {
    const item = status[channel];
    return `${statusLabels[item?.status] || "尚未发送"}${item?.sent_at ? ` · ${new Date(item.sent_at * 1000).toLocaleString("zh-CN")}` : ""}`;
  };
  return <section className="settings-section" id="settings-notifications">
    <div className="section-heading"><h2>通知</h2><span className="subtle-label">外部密钥只显示配置状态</span></div>
    {toggle("desktop_urgent", "桌面通知", "紧急事件显示系统通知。")}
    {toggle("sound_loop", "循环声音", "紧急提醒持续响铃，关闭后立即停止。")}
    {toggle("window_attention", "窗口置顶", "紧急事件唤起并短暂置顶主窗口。")}
    {toggle("server_chan_enabled", "Server酱", "通过 Server酱推送通知。")}
    {secret("server_chan_key", "Server酱 SendKey")}
    {toggle("email_enabled", "邮件", "使用 SMTP SSL 发送邮件。")}
    <div className="setting-row"><strong>SMTP 服务器</strong><Input aria-label="SMTP 服务器" style={{ width: 280 }} value={value("email_smtp_host") || ""} onChange={(event) => change("email_smtp_host", event.target.value)} /></div>
    <div className="setting-row"><strong>SMTP 端口</strong><InputNumber aria-label="SMTP 端口" min={1} max={65535} value={value("email_smtp_port") || 465} onChange={(next) => { if (next !== null) change("email_smtp_port", next); }} /></div>
    <div className="setting-row"><strong>发件账号</strong><Input aria-label="发件账号" style={{ width: 280 }} value={value("email_user") || ""} onChange={(event) => change("email_user", event.target.value)} /></div>
    {secret("email_password", "SMTP 密码")}
    <div className="setting-row"><strong>收件地址</strong><Input aria-label="收件地址" style={{ width: 280 }} value={value("email_to") || ""} onChange={(event) => change("email_to", event.target.value)} /></div>
    {toggle("wecom_webhook_enabled", "企业微信", "通过企业微信机器人 webhook 推送。")}
    {secret("wecom_webhook_url", "企业微信 Webhook")}
    <div className="section-heading"><h3>事件渠道</h3><span className="subtle-label">选择每种事件使用的外部渠道</span></div>
    {events.map(({ id, label }) => <div className="setting-row" key={id}><strong>{label}</strong><div className="button-row">
      {channels.map((channel) => <label key={channel.id}><input type="checkbox" checked={(selectedEvents[id] || []).includes(channel.id)} onChange={(event) => {
        const current = selectedEvents[id] || [];
        const next = event.target.checked ? [...current, channel.id] : current.filter((item) => item !== channel.id);
        change("event_channels", { ...selectedEvents, [id]: next });
      }} /> {channel.label}</label>)}
    </div></div>)}
    <div className="setting-row"><div><strong>试发通知</strong><p>使用固定测试内容，不含乘客或行程信息。编辑后需先保存。</p></div>
      <div className="button-row"><Button type="primary" loading={working === "save"} disabled={!Object.keys(patch).length || working !== null} onClick={() => void save()}>保存通知设置</Button>
      <Button loading={working === "test"} disabled={working !== null} onClick={() => void test()}>发送测试通知</Button></div></div>
    {error && <p role="alert" className="health-warning">{error}</p>}{notice && <p role="status">{notice}</p>}
    <div className="health-list">{channels.map((channel) => <div className="health-row" key={channel.id}><strong>{channel.label}</strong>
      <span>{deliveryLabel(channel.id)}</span></div>)}</div>
  </section>;
}
