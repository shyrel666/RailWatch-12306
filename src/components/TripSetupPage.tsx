import { Button, Input, InputNumber, Select, Switch } from "antd";
import { Save, Search } from "lucide-react";
import { useRailWatchStore } from "../store/useRailWatchStore";
import type { RailWatchConfig } from "../types";
import type { CommandRunner, ConfirmDialog } from "./componentTypes";
import { RiskToggle } from "./DisplayPrimitives";
import { ActionRow, Field, SectionTitle } from "./FormPrimitives";

export function TripSetupPage({
  busy,
  confirm,
  runCommand,
}: {
  busy: string | null;
  confirm: ConfirmDialog;
  runCommand: CommandRunner;
}) {
  const config = useRailWatchStore((state) => state.config);
  const setConfig = useRailWatchStore((state) => state.setConfig);

  const update = (patch: Partial<RailWatchConfig>) => setConfig(patch);
  const guardedAutomation = async (key: "auto_submit" | "auto_alternate", checked: boolean) => {
    if (!checked) {
      update({ [key]: false });
      return;
    }
    const accepted = await confirm(
      key === "auto_submit" ? "启用自动提交" : "启用自动候补",
      key === "auto_submit" ? "自动提交可在发现车票后自动进入订单流程。请确认是否继续。" : "自动候补可在无票时自动提交候补订单。请确认是否继续。",
    );
    update({ [key]: accepted });
  };

  const monitorControls = (
    <>
      <Field label="间隔秒数">
        <InputNumber min={1} max={60} value={config.interval} onChange={(value) => update({ interval: Number(value || 1) })} />
      </Field>
      <Field label="乘客人数">
        <InputNumber min={1} max={20} value={config.passenger_count} onChange={(value) => update({ passenger_count: Number(value || 1) })} />
      </Field>
      <Field label="席别偏好">
        <Select
          value={config.seat_prefer}
          options={["无偏好", "靠窗优先", "靠过道优先"].map((value) => ({ value, label: value }))}
          onChange={(value) => update({ seat_prefer: value })}
        />
      </Field>
      <Field label="预备秒数">
        <InputNumber min={0} max={30} value={config.prepare_time} onChange={(value) => update({ prepare_time: Number(value || 0) })} />
      </Field>
      <Field label="目标时间">
        <input className="native-input" type="time" step="1" value={config.target_time} onChange={(event) => update({ target_time: event.target.value })} />
      </Field>
      <div className="switch-row">
        <Switch checked={config.timer_enabled} onChange={(checked) => update({ timer_enabled: checked })} />
        <span>定时启动</span>
      </div>
      <div className="switch-row">
        <Switch checked={config.keep_alive} onChange={(checked) => update({ keep_alive: checked })} />
        <span>保持会话</span>
      </div>
      <div className="switch-row">
        <Switch checked={config.smart_rate} onChange={(checked) => update({ smart_rate: checked })} />
        <span>智能轮询</span>
      </div>
    </>
  );

  return (
    <div className="trip-setup-grid">
      <section className="content-band trip-form-panel">
        <SectionTitle eyebrow="Quiet Safety Desk" title="行程设置" />
        <div className="field-grid">
          <Field label="出发">
            <Input value={config.from_station_cn} onChange={(event) => update({ from_station_cn: event.target.value })} />
          </Field>
          <Field label="到达">
            <Input value={config.to_station_cn} onChange={(event) => update({ to_station_cn: event.target.value })} />
          </Field>
          <Field label="日期">
            <input className="native-input" type="date" value={config.date} onChange={(event) => update({ date: event.target.value })} />
          </Field>
          <Field label="车次">
            <Input value={config.train_code} onChange={(event) => update({ train_code: event.target.value.toUpperCase() })} />
          </Field>
          <Field label="席别">
            <Input value={config.seat_keyword} onChange={(event) => update({ seat_keyword: event.target.value })} />
          </Field>
          <Field label="乘客">
            <Input value={config.passengers} onChange={(event) => update({ passengers: event.target.value })} />
          </Field>
        </div>
      </section>

      <section className="content-band safety-panel">
        <SectionTitle eyebrow="Safety Review" title="安全确认" />
        <RiskToggle
          checked={config.auto_submit}
          title={config.auto_submit ? "自动提交已启用" : "自动提交关闭"}
          description="发现车票后进入订单流程前必须确认"
          onChange={(checked) => void guardedAutomation("auto_submit", checked)}
        />
        <RiskToggle
          checked={config.auto_alternate}
          title={config.auto_alternate ? "候补排队已启用" : "候补排队关闭"}
          description="仅候补时排队前必须确认"
          onChange={(checked) => void guardedAutomation("auto_alternate", checked)}
        />
        <Field label="候补截止">
          <input className="native-input" type="time" value={config.alternate_deadline} onChange={(event) => update({ alternate_deadline: event.target.value })} />
        </Field>
      </section>

      <section className="content-band trip-monitor-panel">
        <SectionTitle title="轮询与定时" />
        <div className="field-grid compact">{monitorControls}</div>
      </section>

      <ActionRow>
        <Button icon={<Save size={16} />} loading={busy === "saveConfig"} onClick={() => void runCommand("saveConfig", { config }, "设置已保存")}>
          保存
        </Button>
        <Button
          icon={<Search size={16} />}
          loading={busy === "analyzeQuery"}
          onClick={() => void runCommand("analyzeQuery", { config })}
          type="primary"
        >
          分析
        </Button>
      </ActionRow>
    </div>
  );
}
