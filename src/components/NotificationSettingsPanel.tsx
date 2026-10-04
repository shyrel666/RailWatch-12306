import { Button, Input, InputNumber, Switch } from "antd";
import { useEffect, useState, type ReactNode } from "react";
import { AppWindow, MonitorDot, Volume2, type LucideIcon } from "lucide-react";
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
const localToggles: { field: "desktop_urgent" | "sound_loop" | "window_attention"; label: string; detail: string; icon: LucideIcon }[] = [
  { field: "desktop_urgent", label: "桌面通知", detail: "紧急事件显示系统通知。", icon: MonitorDot },
  { field: "sound_loop", label: "循环声音", detail: "紧急提醒持续响铃，关闭后立即停止。", icon: Volume2 },
  { field: "window_attention", label: "窗口置顶", detail: "紧急事件唤起并短暂置顶主窗口。", icon: AppWindow },
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
    return <div className="channel-field wide" key={field}>
      <span>{label}</span>
      <div className="secret-input">
        <Input.Password aria-label={label} value={typeof edited === "string" ? edited : ""} placeholder={configured ? "留空保持原值" : "输入密钥"}
          onChange={(event) => change(field, event.target.value)} />
        <Button disabled={!configured && !edited} onClick={() => change(field, null)}>删除</Button>
      </div>
      <small>{edited === null ? "保存后删除" : typeof edited === "string" && edited ? "保存后替换" : configured ? "已配置；留空保持不变" : "未配置"}</small>
    </div>;
  };
  const text = (field: "email_smtp_host" | "email_user" | "email_to", label: string, placeholder: string, className = "channel-field") => <label className={className} key={field}>
    <span>{label}</span>
    <Input aria-label={label} placeholder={placeholder} value={value(field) || ""} onChange={(event) => change(field, event.target.value)} />
  </label>;
  const enabled = (field: keyof NotificationSettings) => value(field) === true;
  if (!settings) return <section className="settings-section" id="settings-notifications">
    <div className="section-heading"><div className="section-title-copy"><h2>通知</h2><p>{error || "正在加载通知设置…"}</p></div></div>
  </section>;
  const selectedEvents = value("event_channels") || settings.event_channels || Object.fromEntries(events.map(({ id }) => [id, channels.map(({ id: channel }) => channel)])) as NotificationSettings["event_channels"];
  const deliveryLabel = (channel: Channel) => {
    const item = status[channel];
    return `${statusLabels[item?.status] || "尚未发送"}${item?.sent_at ? ` · ${new Date(item.sent_at * 1000).toLocaleString("zh-CN")}` : ""}`;
  };
  const deliveryLamp = (channel: Channel) => {
    const state = status[channel]?.status;
    return state === "success" ? "go" : state === "failed" || state === "queue_full" ? "stop" : state === "queued" ? "wait" : "idle";
  };
  const channelCard = (channel: Channel, field: keyof NotificationSettingsPatch, label: string, detail: string, body: ReactNode) =>
    <article className={"channel-card" + (enabled(field as keyof NotificationSettings) ? " on" : "")} key={channel}>
      <header>
        <div className="channel-title"><strong>{label}</strong><small>{detail}</small></div>
        <div className="channel-delivery"><i className={"lamp " + deliveryLamp(channel)} aria-hidden="true" /><span>{deliveryLabel(channel)}</span></div>
        <Switch aria-label={label} checked={enabled(field as keyof NotificationSettings)} onChange={(next) => change(field, next)} />
      </header>
      <div className="channel-fields">{body}</div>
    </article>;
  const pending = Object.keys(patch).length;
  return <section className="settings-section" id="settings-notifications">
    <div className="section-heading"><div className="section-title-copy"><h2>通知</h2><p>紧急事件的本机提醒与外部推送；外部密钥只显示配置状态。</p></div></div>
    <h3 className="settings-subhead">本机提醒</h3>
    <div className="toggle-grid">
      {localToggles.map((item) => <label className={"toggle-tile" + (enabled(item.field) ? " on" : "")} key={item.field}>
        <span className="toggle-tile-head"><item.icon size={16} aria-hidden="true" />
          <Switch aria-label={item.label} size="small" checked={enabled(item.field)} onChange={(next) => change(item.field, next)} /></span>
        <strong>{item.label}</strong>
        <small>{item.detail}</small>
      </label>)}
    </div>
    <h3 className="settings-subhead">外部渠道</h3>
    <div className="channel-list">
      {channelCard("server_chan", "server_chan_enabled", "Server酱", "通过 Server酱推送通知。", secret("server_chan_key", "Server酱 SendKey"))}
      {channelCard("email", "email_enabled", "邮件", "使用 SMTP SSL 发送邮件。", <>
        {text("email_smtp_host", "SMTP 服务器", "smtp.example.com", "channel-field host")}
        <label className="channel-field narrow"><span>SMTP 端口</span>
          <InputNumber aria-label="SMTP 端口" min={1} max={65535} value={value("email_smtp_port") || 465} onChange={(next) => { if (next !== null) change("email_smtp_port", next); }} /></label>
        {text("email_user", "发件账号", "name@example.com")}
        {text("email_to", "收件地址", "name@example.com")}
        {secret("email_password", "SMTP 密码")}
      </>)}
      {channelCard("wecom_webhook", "wecom_webhook_enabled", "企业微信", "通过企业微信机器人 webhook 推送。", secret("wecom_webhook_url", "企业微信 Webhook"))}
    </div>
    <div className="settings-subhead-row"><h3 className="settings-subhead">事件渠道</h3><span className="subtle-label">选择每种事件使用的外部渠道</span></div>
    <div className="channel-matrix-wrap">
      <table className="channel-matrix">
        <thead><tr><th scope="col">事件</th>{channels.map((channel) => <th scope="col" key={channel.id}>{channel.label}</th>)}</tr></thead>
        <tbody>{events.map(({ id, label }) => <tr key={id}><th scope="row">{label}</th>
          {channels.map((channel) => <td key={channel.id}><input type="checkbox" aria-label={`${label} · ${channel.label}`}
            checked={(selectedEvents[id] || []).includes(channel.id)} onChange={(event) => {
              const current = selectedEvents[id] || [];
              const next = event.target.checked ? [...current, channel.id] : current.filter((item) => item !== channel.id);
              change("event_channels", { ...selectedEvents, [id]: next });
            }} /></td>)}
        </tr>)}</tbody>
      </table>
    </div>
    <div className={"notify-footer" + (pending ? " dirty" : "")}>
      <div><strong>{pending ? "有未保存的修改" : "试发通知"}</strong><p>测试通知使用固定内容，不含乘客或行程信息；编辑后需先保存。</p></div>
      <div className="button-row">
        <Button loading={working === "test"} disabled={working !== null} onClick={() => void test()}>发送测试通知</Button>
        <Button type="primary" loading={working === "save"} disabled={!pending || working !== null} onClick={() => void save()}>保存通知设置</Button>
      </div>
    </div>
    {error && <p role="alert" className="settings-error">{error}</p>}{notice && <p role="status" className="settings-notice">{notice}</p>}
  </section>;
}
