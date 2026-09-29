import { useEffect, useState } from "react";
import { Button, Checkbox, Modal, Popover } from "antd";
import { CircleHelp, ClipboardCheck } from "lucide-react";
import { useRailWatchStore } from "../store/useRailWatchStore";
import { railwatchStore, tripFingerprint } from "../store/railwatchStore";
import { useClock } from "../lib/useClock";
import { railwatchApi } from "../lib/railwatchApi";
import { hasUnresolvedOrder } from "../lib/dashboardState";
import { checkLabels, rehearsalDisabled, rehearsalExpired, verdictLabels, type RehearsalCheck, type RehearsalReport } from "../lib/rehearsal";
import { TimelineWaterfall } from "./TimelineWaterfall";
import type { CommandRunner } from "./componentTypes";

const verdictSummary = { ready: "开售时的主要路径已验证", blocked: "当前配置存在会阻止执行的步骤", risky: "请查看检查结果", cancelled: "本次彩排未完成" };

const timelineHelp = <div className="rehearsal-timeline-help-content">
  <p>T0 表示起售时刻。绿色条按阶段先后排列，长度表示预计耗时，并非实时进度。</p>
  <ul>
    <li><strong>唤醒迟到：</strong>定时程序到点后，实际开始执行的延迟。</li>
    <li><strong>查询往返：</strong>发起一次余票查询到收到结果的时间。</li>
    <li><strong>下单页与核对：</strong>命中余票后，进入下单页、核对信息到提交的时间。</li>
    <li><strong>确认弹窗：</strong>提交后到完成确认弹窗操作的时间。</li>
    <li><strong>官方处理：</strong>发出确认后到本机观察到订单结果的时间，包含等待和结果检测。</li>
  </ul>
  <p><strong>数据来源：</strong>“本机实测”来自本次彩排；唤醒延迟取多次采样的 P95（约 95% 的样本不超过该值）。“历史中位数”取历史耗时中居中的值；本地脚本耗时不含官方页面加载。缺少数据的阶段标为未知。</p>
  <p><strong>有什么用：</strong>帮助判断耗时集中在哪个阶段，并与实际运行复盘对照。</p>
  <p>合计仅包含已知阶段，不含反复查票、未知阶段或支付时间，不代表购票成功率或官方处理承诺。</p>
</div>;

function finishedAt(report: RehearsalReport) {
  return new Date(report.finished_at * 1000).toLocaleString("zh-CN", { hour12: false, month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function countChecks(checks: RehearsalCheck[]) {
  const counts = { pass: 0, warn: 0, fail: 0, unknown: 0 };
  for (const check of checks) if (check.status && check.status in counts) counts[check.status as keyof typeof counts] += 1;
  return [["pass", counts.pass], ["warn", counts.warn], ["fail", counts.fail], ["unknown", counts.unknown]] as const;
}

export function RehearsalPanel({ busy, runCommand }: { busy: string | null; runCommand: CommandRunner }) {
  const config = useRailWatchStore(s => s.config);
  const status = useRailWatchStore(s => s.status);
  const rehearsal = useRailWatchStore(s => s.rehearsal);
  const navigate = useRailWatchStore(s => s.setActivePage);
  const [sendTest, setSendTest] = useState(false);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const [clearing, setClearing] = useState(false);
  const now = useClock();
  const report = rehearsal.report;
  const active = !!rehearsal.activeId;
  const checks = active ? rehearsal.checks : report?.checks ?? [];
  const stale = report && rehearsalExpired(rehearsal.fingerprint, tripFingerprint(config));
  const disabled = rehearsalDisabled(config, now, status.monitoring, hasUnresolvedOrder(status.order),
    !!busy || clearing || status.activity?.state === "busy", report?.started_at ?? rehearsal.lastStartedAt);
  const done = rehearsal.checks.filter(check => check.status).length;
  // A manual run opens the dialog so progress is visible; task-triggered runs
  // stay in the panel because the user may not be looking at this page.
  useEffect(() => { if (rehearsal.activeId && rehearsal.trigger === "manual") setOpen(true); }, [rehearsal.activeId, rehearsal.trigger]);
  const start = async () => {
    const snapshot = structuredClone(config);
    railwatchStore.getState().prepareRehearsal(snapshot);
    await runCommand("rehearse", { config: snapshot, options: { send_test_notification: sendTest } });
    railwatchStore.getState().resetRehearsalProgress();
  };
  const cancel = async () => {
    setError("");
    try { await railwatchApi.command("cancelRehearsal"); }
    catch { setError("取消请求未送达，请稍后重试。"); }
  };
  const clearHistory = async () => {
    setError("");
    setClearing(true);
    try {
      const result = await railwatchApi.command<{ cleared?: number; cancelled?: boolean }>("clearRehearsalHistory");
      if (typeof result?.cleared === "number") {
        railwatchStore.getState().clearRehearsalHistory();
        setOpen(false);
      }
    } catch { setError("清除失败，彩排记录已保留，请稍后重试。"); }
    finally { setClearing(false); }
  };
  const applyFix = (check: RehearsalCheck) => {
    // Same fields as TimerSettings' "设为起售时间", so its mismatch hint keeps working.
    if (check.fix?.sale_at && !stale) railwatchStore.getState().setConfig({
      sale_at: check.fix.sale_at, timer_enabled: true, target_time: check.fix.sale_at.slice(11, 19), sale_time_source: "12306",
      sale_time_checked_at: new Date((check.fix.checked_at ?? Date.now() / 1000) * 1000).toISOString() });
    setOpen(false);
    navigate(check.fix!.page, check.fix!.section);
  };
  const title = active ? `彩排进行中 · 已完成 ${done}/${rehearsal.checks.length}` : "起售彩排结果";
  return <section id="monitor-rehearsal" tabIndex={-1} className="rehearsal-panel rehearsal-compact" aria-label="起售彩排">
    <div className="rehearsal-header"><div className="rehearsal-intro"><h2>起售彩排</h2><p>开售前检查主要路径；离线演练仅验证 RailWatch 自身的核对逻辑。</p></div>
      <div className="rehearsal-actions">
        <Checkbox checked={sendTest} disabled={active || !!busy || clearing || status.monitoring} onChange={e => setSendTest(e.target.checked)}>同时发送测试提醒</Checkbox>
        {active ? <Button onClick={() => setOpen(true)}>查看进度</Button> : report ? <>
          <Button onClick={() => setOpen(true)}>查看结果</Button>
          <Button disabled={!!busy || status.monitoring || status.activity?.state === "busy"} loading={clearing} onClick={() => void clearHistory()}>清除记录</Button>
        </> : null}
      {active && rehearsal.trigger === "manual" ? <Button onClick={() => void cancel()}>取消彩排</Button> :
        <Button disabled={!!disabled || active} loading={busy === "rehearse"} onClick={() => void start()}>开始彩排</Button>}
      </div>
    </div>
    {disabled && !active ? <p role="status">{disabled}</p> : null}
    {active && rehearsal.trigger === "task" ? <p>随定时任务执行；停止任务会同时取消彩排。</p> : null}
    {error ? <p role="alert">{error}</p> : null}
    {active ? <div className="rehearsal-summary"><p role="status">彩排进行中 · 已完成 {done}/{rehearsal.checks.length} 项检查</p></div> : null}
    {report && !active ? <div className="rehearsal-summary">
      <p className={`rehearsal-verdict ${report.verdict}`}><strong>{verdictLabels[report.verdict]}</strong> · {finishedAt(report)} 完成 ·
        {countChecks(report.checks).filter(([, count]) => count).map(([key, count]) => ` ${count} ${checkLabels[key]}`).join(" ·")}</p>
      {stale ? <p role="status" className="rehearsal-warning">行程已修改或来自历史记录，彩排结果已过期</p> : null}
    </div> : null}
    {!status.monitoring && status.task?.run_id ? <Button onClick={() => navigate("订单中心", "order-run-reviews")}>查看本次复盘</Button> : null}
    <Modal open={open} centered width={820} className="railwatch-dialog rehearsal-dialog" onCancel={() => setOpen(false)}
      title={<span className="dialog-title"><ClipboardCheck size={18} />{title}</span>}
      footer={<>{active && rehearsal.trigger === "manual" ? <Button onClick={() => void cancel()}>取消彩排</Button> : null}
        <Button type="primary" onClick={() => setOpen(false)}>关闭</Button></>}>
      <div className="rehearsal-dialog-body">
        {stale && !active ? <p role="status" className="rehearsal-warning">行程已修改或来自历史记录，彩排结果已过期</p> : null}
        {report && !active ? <p className={`rehearsal-verdict ${report.verdict}`}><strong>{verdictLabels[report.verdict]}</strong> · {verdictSummary[report.verdict]}</p> : null}
        <ol className="rehearsal-checks">{checks.map(check => <li key={check.id} className={`rehearsal-check ${check.status ?? "waiting"}`}>
          <span>{check.status ? checkLabels[check.status] : "待检查"}</span><div><strong>{check.title}</strong><p>{check.summary}</p>
            {check.details?.map((detail, index) => <small key={index}>{detail}</small>)}</div>
          <small>{check.duration_ms !== undefined ? `${(check.duration_ms / 1000).toFixed(2)} 秒` : ""}</small>
          {check.fix && check.status !== "pass" && !active ? <Button size="small" onClick={() => applyFix(check)}>
            {check.fix.sale_at && stale ? "核对定时" : check.fix.label}</Button> : null}
        </li>)}</ol>
        {!active && report?.prediction ? <>
          <h3 className="rehearsal-timeline-heading">
            预测时间线 · T0 起售
            <Popover title="如何理解预测时间线" content={timelineHelp} trigger={["hover", "focus"]} placement="topLeft">
              <button type="button" className="rehearsal-timeline-help" aria-label="预测时间线说明">
                <CircleHelp size={14} aria-hidden="true" />
              </button>
            </Popover>
          </h3>
          <TimelineWaterfall segments={report.prediction} />
        </> : null}
      </div>
    </Modal>
  </section>;
}
