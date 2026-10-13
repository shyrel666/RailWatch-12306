import { useEffect, useState } from "react";
import { Button, InputNumber, Modal, Select, Switch } from "antd";
import { ClipboardCheck, Settings2, Ticket, TicketPlus, type LucideIcon } from "lucide-react";
import { AlternateSettings } from "./AlternateSettings";
import { Hint } from "./DisplayPrimitives";
import { PreferenceSection } from "./PreferenceSection";
import { ORDER_POLICY } from "../lib/orderPolicy";
import { useRailWatchStore } from "../store/useRailWatchStore";
import type { RailWatchConfig } from "../types";
import type { CommandRunner, ConfirmDialog } from "./componentTypes";

const ALTERNATE_MODES = [{ value: "single", label: "首个可用组合" }, { value: "multiple", label: "多个已配置组合" }];

function AutomationToggle({ checked, title, description, trigger, icon: Icon, onChange, onConfigure }: {
  checked: boolean;
  title: string;
  description: string;
  trigger: string;
  icon: LucideIcon;
  onChange: (checked: boolean) => void;
  onConfigure?: () => void;
}) {
  return <article className={`automation-feature${checked ? " active" : ""}`}>
    <div className="automation-feature-head">
      <span className="automation-feature-icon"><Icon size={17} aria-hidden="true" /></span>
      <span className="automation-feature-trigger">{trigger}</span>
      <Switch aria-label={`${title}，${description}`} checked={checked} onChange={onChange} />
    </div>
    <div className="automation-feature-title">
      <strong>{title}</strong>
      {checked && onConfigure ? <Button type="link" size="small" icon={<Settings2 size={13} />}
        aria-haspopup="dialog" onClick={onConfigure}>配置</Button> : null}
    </div>
    <small>{description}</small>
  </article>;
}

// Only an explicit waitlist activation opens its configuration dialog.
export function AutomationSection({ config, update, runCommand, confirm, busy }: {
  config: RailWatchConfig;
  update: (patch: Partial<RailWatchConfig>) => void;
  runCommand: CommandRunner;
  confirm: ConfirmDialog;
  busy: string | null;
}) {
  const [open, setOpen] = useState(false);
  const monitoring = useRailWatchStore(state => state.status.monitoring);

  const guardedAutomation = async (key: "auto_submit" | "auto_alternate", checked: boolean) => {
    if (!checked) {
      update({ [key]: false });
      return;
    }
    const accepted = await confirm(
      key === "auto_submit" ? "启用自动提交" : "启用自动候补",
      key === "auto_submit"
        ? "发现余票后，将按设置的车次、日期、乘客和席别自动提交订单并确认官方弹窗。登录核验与支付仍由你完成。"
        : "将按已保存的候补方案自动提交，并确认官网的静音车厢与提交提示。待支付时会通知你完成预付款。",
    );
    update({ [key]: accepted });
    if (key === "auto_alternate" && accepted) setOpen(true);
  };

  useEffect(() => { if (!config.auto_alternate) setOpen(false); }, [config.auto_alternate]);
  const watchEnabled = config.order_watch_enabled ?? ORDER_POLICY.order_watch_enabled;
  const watchInterval = config.order_watch_interval_seconds ?? ORDER_POLICY.order_watch_interval_seconds;
  const description = [config.auto_submit ? "自动提交" : "", config.auto_alternate ? "自动候补" : ""]
    .filter(Boolean).join(" · ") || "仅查询与提醒";

  return <>
    <PreferenceSection id="trip-automation" title="自动化" description={description}
      defaultOpen>
      <div className="trip-automation-toggles">
        <AutomationToggle
          checked={config.auto_submit}
          icon={Ticket}
          trigger="有票时"
          title={config.auto_submit ? "自动提交已开启" : "自动提交已关闭"}
          description="有票时自动提交订单并确认，支付由你完成。"
          onChange={checked => void guardedAutomation("auto_submit", checked)}
        />
        <AutomationToggle
          checked={config.auto_alternate}
          icon={TicketPlus}
          trigger="无票时"
          title={config.auto_alternate ? "自动候补已开启" : "自动候补已关闭"}
          description="无票时自动提交候补，预付款由你支付。"
          onChange={checked => void guardedAutomation("auto_alternate", checked)}
          onConfigure={() => setOpen(true)}
        />
      </div>
      {/* Order tracking follows both kinds of orders, so it stays outside the waitlist dialog;
          a single row keeps this column close to the height of the trip form beside it. */}
      {config.auto_submit || config.auto_alternate ? <section className="trip-automation-watch" aria-label="订单跟踪">
        <span className="trip-automation-watch-label">
          <ClipboardCheck size={16} aria-hidden="true" />
          <strong>持续订单核对</strong>
          <Hint text="取得订单号后在独立标签页按间隔核对状态，保留付款页面；候补生效后持续等待兑现。可在订单中心停止，重启应用后点击「继续核对」恢复。" />
        </span>
        {watchEnabled ? <InputNumber aria-label="订单核对间隔（秒）" className="trip-automation-watch-interval" precision={0}
          prefix="每" suffix="秒"
          min={ORDER_POLICY.min_watch_interval_seconds} max={ORDER_POLICY.max_watch_interval_seconds}
          value={watchInterval}
          onChange={value => { if (value !== null) update({ order_watch_interval_seconds: value }); }} /> : null}
        <Switch aria-label="持续订单核对" checked={watchEnabled} onChange={value => update({ order_watch_enabled: value })} />
      </section> : null}
    </PreferenceSection>
    <Modal
      open={open && config.auto_alternate}
      title={<div className="automation-dialog-title">
        <span className="automation-dialog-symbol"><TicketPlus size={22} aria-hidden="true" /></span>
        <div><span>候补配置</span><p>余票不足时，按此方案提交候补并跟踪兑现进度。</p></div>
      </div>}
      className="automation-dialog"
      width={740}
      centered
      destroyOnHidden
      onCancel={() => setOpen(false)}
      footer={<div className="automation-dialog-footer">
        <span>完成后，请在行程设置中保存更改</span>
        <Button type="primary" onClick={() => setOpen(false)}>完成</Button>
      </div>}
    >
      <div className="automation-dialog-body">
        <section className="alternate-config-section" aria-label="候补方案">
          <div className="alternate-config-heading">
            <TicketPlus size={16} aria-hidden="true" /><h3>候补方案</h3>
          </div>
          <div className="alternate-config-row">
            <div className="alternate-config-copy">
              <span className="trip-field-label-with-help">组合方式
                <Hint text={`多个组合：在官网「添加备选方案」中按已配置的日期（最多 ${ORDER_POLICY.max_dates} 个）、车次和席别选择，统一核对后提交为一个候补订单，清单可在订单中心查看。`} /></span>
              <p>{config.alternate_mode === "multiple" ? "将多个日期、车次与席别组合提交为一个候补订单。" : "提交首个可用的日期、车次与席别组合。"}</p>
            </div>
            <Select aria-label="候补组合" className="trip-select" value={config.alternate_mode ?? "single"}
              options={ALTERNATE_MODES} onChange={value => update({ alternate_mode: value })} />
          </div>
          {config.alternate_mode === "multiple" ? <div className="alternate-config-row">
            <div className="alternate-config-copy"><span>组合上限</span><p>限制同一候补订单中的备选组合数量。</p></div>
            <div className="alternate-config-compact-control">
              <InputNumber aria-label="候补组合上限" className="trip-select" min={1} max={ORDER_POLICY.max_combinations} precision={0}
                suffix="个"
                value={config.alternate_max_combinations ?? ORDER_POLICY.alternate_max_combinations}
                onChange={value => { if (value !== null) update({ alternate_max_combinations: value }); }} />
            </div>
          </div> : null}
        </section>
        <AlternateSettings config={config} update={update} runCommand={runCommand} disabled={Boolean(busy) || monitoring} />
      </div>
    </Modal>
  </>;
}
