# RailWatch Desktop UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the RailWatch renderer UI as a premium macOS-style dark desktop tool with an option-2 dispatch Dashboard and an option-3 quiet safety Trip Setup page.

**Architecture:** Keep the current Electron + React renderer boundary. Centralize visual language in shared primitives and `src/styles.css`, then update each page without touching Electron main, preload, Python runtime, or Selenium core. Dashboard and Trip Setup stay separate pages with separate layouts.

**Tech Stack:** React 19, TypeScript, Ant Design 6, Zustand, lucide-react, Vitest, Testing Library, Vite.

---

## Scope Check

This is one renderer UI subsystem. It does not need to be split into separate specs because every task works against the same shell, theme, component primitives, and page-level renderer code.

## File Structure

- Modify `src/App.tsx`: align Ant Design tokens with the new theme and keep dark-mode preference wiring.
- Modify `src/types.ts`: keep the page contract stable with `RailWatchPage = "仪表盘" | "行程设置" | "监控" | "设置"`.
- Modify `src/store/railwatchStore.ts`: keep `activePage` defaults and route transitions aligned to the stable page contract.
- Modify `src/components/Shell.tsx`: macOS-style shell, stable page navigation, event-panel close wiring.
- Modify `src/components/DisplayPrimitives.tsx`: reusable badges, metric cards, workflow stepper, empty states, and risk toggles.
- Modify `src/components/FormPrimitives.tsx`: reusable labeled fields, section titles, helper text, and action rows.
- Modify `src/components/DashboardPage.tsx`: option-2 dispatch dashboard with workflow, route summary, readiness cards, risk panel, and hits table.
- Modify `src/components/TripSetupPage.tsx`: option-3 quiet safety form with main form and safety review column.
- Modify `src/components/MonitorPage.tsx`: operational monitor controls and compact query table.
- Modify `src/components/SettingsPage.tsx`: settings surfaces with appearance, local data, environment actions, and destructive actions separated.
- Modify `src/components/EventPanel.tsx`: drawer-style event feed with close action, severity sorting, pause state, and icon controls.
- Modify `src/styles.css`: shared tokens, dark/light themes, shell, page, primitive, form, table, and event-panel styles.
- Modify tests in `src/components/*.test.tsx` to encode page boundaries and safety behavior.

## Task 1: Stabilize Page Contract And Shell

**Files:**
- Modify: `src/types.ts`
- Modify: `src/store/railwatchStore.ts`
- Modify: `src/App.tsx`
- Modify: `src/components/Shell.tsx`
- Test: `src/components/Shell.test.tsx`

- [ ] **Step 1: Write the shell contract test**

Replace `src/components/Shell.test.tsx` with:

```tsx
// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";
import { defaultRuntimeInfo, defaultStatus } from "../store/railwatchStore";
import { RAILWATCH_PAGES, ShellLayout, SidebarNav } from "./Shell";

describe("SidebarNav", () => {
  test("keeps stable page names and reports navigation clicks", async () => {
    const user = userEvent.setup();
    const onPageChange = vi.fn();

    expect(RAILWATCH_PAGES.map((page) => page.name)).toEqual(["仪表盘", "行程设置", "监控", "设置"]);

    render(
      <SidebarNav
        activePage="仪表盘"
        appName="RailWatch 12306"
        dataDir="D:/RailWatch/data"
        phase="idle"
        onPageChange={onPageChange}
      />,
    );

    expect(screen.getByText("RailWatch 12306")).toBeTruthy();
    expect(screen.getByText("D:/RailWatch/data")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: /行程设置/ }));

    expect(onPageChange).toHaveBeenCalledWith("行程设置");
  });
});

describe("ShellLayout", () => {
  test("renders the desktop shell and can toggle the event panel", async () => {
    const user = userEvent.setup();
    const onToggleEventPanel = vi.fn();

    render(
      <ShellLayout
        activePage="监控"
        darkMode
        eventPanel={<aside>事件面板</aside>}
        eventPanelVisible
        runtime={{ ...defaultRuntimeInfo, app_display_name: "RailWatch 12306", data_dir: "D:/RailWatch/data" }}
        status={{ ...defaultStatus, summary: "查询已解析", status_message: "就绪" }}
        onPageChange={vi.fn()}
        onToggleEventPanel={onToggleEventPanel}
      >
        <div>监控内容</div>
      </ShellLayout>,
    );

    expect(screen.getByRole("heading", { name: "监控" })).toBeTruthy();
    expect(screen.getByText("查询已解析")).toBeTruthy();
    expect(screen.getByText("监控内容")).toBeTruthy();
    expect(screen.getByText("事件面板")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "隐藏事件" }));

    expect(onToggleEventPanel).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run the shell test and verify it fails on the current contract**

Run: `npm run test:renderer -- src/components/Shell.test.tsx`

Expected: FAIL because current navigation includes `购票监控` and shell styling/labels are not yet aligned.

- [ ] **Step 3: Implement stable page names and shell event close wiring**

Make these edits:

```tsx
// src/types.ts
export type RailWatchPage = "仪表盘" | "行程设置" | "监控" | "设置";
```

```ts
// src/store/railwatchStore.ts
applyResults: (payload) => {
  set({ results: payload.rows, activePage: "监控" });
},
```

```tsx
// src/App.tsx content routing
if (activePage === "监控") {
  return <MonitorPage busy={busy} runCommand={runCommand} />;
}
```

```tsx
// src/components/Shell.tsx page list
export const RAILWATCH_PAGES: { name: string; icon: LucideIcon }[] = [
  { name: "仪表盘", icon: Gauge },
  { name: "行程设置", icon: TrainFront },
  { name: "监控", icon: MonitorPlay },
  { name: "设置", icon: Settings },
];
```

Keep `MonitorPage` section text as `购票监控` where it is descriptive content. Use `监控` as the route identity.

- [ ] **Step 4: Run the shell test and verify it passes**

Run: `npm run test:renderer -- src/components/Shell.test.tsx`

Expected: PASS.

- [ ] **Step 5: Commit the shell contract**

```bash
git add src/types.ts src/store/railwatchStore.ts src/App.tsx src/components/Shell.tsx src/components/Shell.test.tsx
git commit -m "Align renderer page contract"
```

## Task 2: Build Shared Display And Form Primitives

**Files:**
- Modify: `src/components/DisplayPrimitives.tsx`
- Modify: `src/components/FormPrimitives.tsx`
- Modify: `src/styles.css`
- Create: `src/components/DisplayPrimitives.test.tsx`
- Create: `src/components/FormPrimitives.test.tsx`

- [ ] **Step 1: Write primitive smoke tests**

Create `src/components/DisplayPrimitives.test.tsx`:

```tsx
// @vitest-environment jsdom
import { render, screen, within } from "@testing-library/react";
import { CircleDot, Gauge } from "lucide-react";
import { describe, expect, test } from "vitest";
import { EmptyState, MetricCard, StatusBadge, WorkflowStepper } from "./DisplayPrimitives";

describe("DisplayPrimitives", () => {
  test("renders badges, metric cards, empty states, and workflow steps", () => {
    render(
      <div>
        <StatusBadge tone="green">可用</StatusBadge>
        <MetricCard title="环境" body="ChromeDriver 已通过" meta="可用" tone="green" icon={Gauge} />
        <WorkflowStepper steps={[{ label: "环境检查", description: "先确认本机依赖", icon: CircleDot, state: "current" }]} />
        <EmptyState title="暂无命中" description="等待目标席别出现" />
      </div>,
    );

    expect(screen.getByText("可用")).toBeTruthy();
    expect(screen.getByLabelText("环境: ChromeDriver 已通过")).toBeTruthy();
    const workflow = screen.getByRole("list", { name: "监控流程" });
    expect(within(workflow).getByText("环境检查")).toBeTruthy();
    expect(screen.getByText("暂无命中")).toBeTruthy();
  });
});
```

Create `src/components/FormPrimitives.test.tsx`:

```tsx
// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { ActionRow, Field, SectionTitle } from "./FormPrimitives";

describe("FormPrimitives", () => {
  test("renders accessible field labels, section titles, and action rows", () => {
    render(
      <section>
        <SectionTitle eyebrow="Quiet Safety Desk" title="行程设置" action={<button type="button">帮助</button>} />
        <Field label="车次" description="输入后自动转为大写">
          <input />
        </Field>
        <ActionRow>
          <button type="button">保存</button>
        </ActionRow>
      </section>,
    );

    expect(screen.getByText("Quiet Safety Desk")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "行程设置" })).toBeTruthy();
    expect(screen.getByLabelText("车次")).toBeTruthy();
    expect(screen.getByText("输入后自动转为大写")).toBeTruthy();
    expect(screen.getByRole("button", { name: "保存" })).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run primitive smoke tests and verify they fail**

Run: `npm run test:renderer -- src/components/DisplayPrimitives.test.tsx src/components/FormPrimitives.test.tsx`

Expected: FAIL because `FormPrimitives` does not export `ActionRow` and `DisplayPrimitives` styles/exports may not yet match the smoke tests.

- [ ] **Step 3: Update `DisplayPrimitives.tsx`**

Use these exported primitives:

```tsx
import type { ReactNode } from "react";
import { Switch } from "antd";
import { CheckCircle2, CircleDot, Clock3 } from "lucide-react";
import type { LucideIcon } from "lucide-react";

export type Tone = "amber" | "blue" | "green" | "indigo" | "red" | "slate" | "teal";

export function StatusBadge({ children, tone = "slate" }: { children: ReactNode; tone?: Tone }) {
  return <span className={`status-badge ${tone}`}>{children}</span>;
}

export function MetricCard({
  body,
  icon: Icon,
  meta,
  tone,
  title,
}: {
  body: string;
  icon: LucideIcon;
  meta: string;
  tone: Tone;
  title: string;
}) {
  return (
    <article className={`metric-card ${tone}`} aria-label={`${title}: ${body}`}>
      <div className="metric-icon">
        <Icon size={21} />
      </div>
      <div>
        <div className="metric-card-head">
          <strong>{title}</strong>
          <StatusBadge tone={tone}>{meta}</StatusBadge>
        </div>
        <p>{body}</p>
      </div>
    </article>
  );
}

export function EmptyState({ description, title }: { description: string; title: string }) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      <span>{description}</span>
    </div>
  );
}

export type WorkflowStep = {
  description: string;
  icon: LucideIcon;
  label: string;
  state: "current" | "done" | "pending";
};

const workflowStateText: Record<WorkflowStep["state"], string> = {
  current: "当前",
  done: "完成",
  pending: "待办",
};

const workflowStateIcon: Record<WorkflowStep["state"], LucideIcon> = {
  current: CircleDot,
  done: CheckCircle2,
  pending: Clock3,
};

export function WorkflowStepper({ steps }: { steps: WorkflowStep[] }) {
  return (
    <ol className="workflow-stepper" aria-label="监控流程">
      {steps.map((step) => {
        const StepIcon = step.icon;
        const StateIcon = workflowStateIcon[step.state];
        return (
          <li className={`workflow-step ${step.state}`} key={step.label} aria-current={step.state === "current" ? "step" : undefined}>
            <span className="workflow-rail">
              <StepIcon size={17} />
            </span>
            <span className="workflow-copy">
              <strong>{step.label}</strong>
              <small>{step.description}</small>
            </span>
            <span className="workflow-state">
              <StateIcon size={14} />
              {workflowStateText[step.state]}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

export function RiskToggle({
  checked,
  description,
  onChange,
  title,
}: {
  checked: boolean;
  description: string;
  onChange: (checked: boolean) => void;
  title: string;
}) {
  return (
    <label className={checked ? "risk-toggle active" : "risk-toggle"}>
      <Switch checked={checked} onChange={onChange} />
      <span>
        <strong>{title}</strong>
        <small>{description}</small>
      </span>
    </label>
  );
}
```

- [ ] **Step 4: Update `FormPrimitives.tsx`**

Use these exported form helpers:

```tsx
import type { ReactNode } from "react";

export function Field({ children, description, label }: { children: ReactNode; description?: string; label: string }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {description ? <small>{description}</small> : null}
    </label>
  );
}

export function SectionTitle({ action, eyebrow, title }: { action?: ReactNode; eyebrow?: string; title: string }) {
  return (
    <div className="section-title">
      <div>
        {eyebrow ? <span>{eyebrow}</span> : null}
        <h2>{title}</h2>
      </div>
      {action}
    </div>
  );
}

export function ActionRow({ children }: { children: ReactNode }) {
  return <div className="form-actions">{children}</div>;
}
```

- [ ] **Step 5: Add primitive CSS selectors**

Append these selectors to `src/styles.css` during this task, then refine full theme in Task 7:

```css
.status-badge,
.workflow-state {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-height: 24px;
  border-radius: 999px;
  padding: 0 9px;
  font-size: 12px;
  color: var(--muted);
  background: var(--surface-muted);
}

.metric-card,
.risk-toggle,
.empty-state {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
}

.workflow-stepper {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}
```

- [ ] **Step 6: Run primitive smoke tests and verify they pass**

Run: `npm run test:renderer -- src/components/DisplayPrimitives.test.tsx src/components/FormPrimitives.test.tsx`

Expected: PASS.

- [ ] **Step 7: Commit shared primitives**

```bash
git add src/components/DisplayPrimitives.tsx src/components/FormPrimitives.tsx src/components/DisplayPrimitives.test.tsx src/components/FormPrimitives.test.tsx src/styles.css
git commit -m "Add shared renderer UI primitives"
```

## Task 3: Implement Option-2 Dispatch Dashboard

**Files:**
- Modify: `src/components/DashboardPage.tsx`
- Modify: `src/components/DashboardPage.test.tsx`
- Modify: `src/styles.css`

- [ ] **Step 1: Replace Dashboard tests with dispatch-dashboard expectations**

Keep the existing reset helper and use these tests:

```tsx
test("guides the user to check the environment first and hides raw risk codes", async () => {
  const user = userEvent.setup();

  render(<DashboardPage />);

  expect(screen.getByRole("heading", { name: "下一步" })).toBeTruthy();
  expect(screen.getByRole("button", { name: /检查环境/ })).toBeTruthy();
  expect(screen.getByText("低风险")).toBeTruthy();
  expect(screen.queryByText("notice")).toBeNull();

  await user.click(screen.getByRole("button", { name: /检查环境/ }));

  expect(railwatchStore.getState().activePage).toBe("设置");
});

test("shows the operational workflow and keeps setup fields off the dashboard", () => {
  render(<DashboardPage />);

  const workflow = screen.getByRole("list", { name: "监控流程" });
  const steps = within(workflow).getAllByRole("listitem");

  expect(steps).toHaveLength(6);
  expect(steps[0].textContent).toContain("环境检查");
  expect(steps[0].textContent).toContain("当前");
  expect(steps[5].textContent).toContain("命中提醒");
  expect(screen.getByLabelText("当前路线")).toBeTruthy();
  expect(screen.getByRole("heading", { name: "就绪状态" })).toBeTruthy();
  expect(screen.getByRole("heading", { name: "监控结果" })).toBeTruthy();
  expect(screen.getByRole("heading", { name: "风险控制" })).toBeTruthy();
  expect(screen.queryByLabelText("乘客")).toBeNull();
});
```

- [ ] **Step 2: Run Dashboard tests and verify they fail**

Run: `npm run test:renderer -- src/components/DashboardPage.test.tsx`

Expected: FAIL because `DashboardPage` still renders status cards and does not expose dispatch workflow sections.

- [ ] **Step 3: Add Dashboard helper functions**

Inside `src/components/DashboardPage.tsx`, define:

```tsx
const riskLabel: Record<string, string> = {
  notice: "低风险",
  success: "低风险",
  active: "监控中",
  warning: "需注意",
  critical: "高风险",
};

function getWorkflowSteps(status: RailWatchStatus, hasHits: boolean): WorkflowStep[] {
  const hitDone = hasHits;
  return [
    {
      label: "环境检查",
      description: status.environment_ready ? "ChromeDriver 可用" : "先确认本机依赖",
      icon: Database,
      state: status.environment_ready ? "done" : "current",
    },
    {
      label: "人工登录",
      description: status.login_ready ? "登录页已打开" : "打开 12306 登录页",
      icon: LogIn,
      state: !status.environment_ready ? "pending" : status.login_ready ? "done" : "current",
    },
    {
      label: "查询分析",
      description: status.query_ready ? "页面结果已解析" : "保存行程后分析",
      icon: Search,
      state: !status.login_ready ? "pending" : status.query_ready ? "done" : "current",
    },
    {
      label: "启动监控",
      description: status.monitoring ? "受控刷新中" : "等待启动",
      icon: Radar,
      state: !status.query_ready ? "pending" : status.monitoring || hitDone ? "done" : "current",
    },
    {
      label: "命中提醒",
      description: hitDone ? "已有目标票命中" : "等待目标席别",
      icon: Bell,
      state: hitDone ? "current" : "pending",
    },
    {
      label: "人工确认",
      description: "订单确认和支付仍人工完成",
      icon: ShieldAlert,
      state: hitDone ? "current" : "pending",
    },
  ];
}
```

- [ ] **Step 4: Replace Dashboard render with dispatch layout**

Use:

```tsx
return (
  <div className="dashboard-grid dispatch-dashboard">
    <section className="dispatch-hero" aria-label="当前路线">
      <div>
        <span>当前路线</span>
        <strong>{config.from_station_cn || "出发站"} → {config.to_station_cn || "到达站"}</strong>
        <small>{config.date || "未选择日期"} · {config.train_code || "未指定车次"} · {config.seat_keyword || "未指定席别"}</small>
      </div>
      <StatusBadge tone={status.monitoring ? "teal" : "slate"}>{status.monitoring ? "监控中" : "待启动"}</StatusBadge>
    </section>

    <section className="content-band dispatch-flow">
      <SectionTitle eyebrow="Rail Dispatch" title="监控流程" />
      <WorkflowStepper steps={getWorkflowSteps(status, hits.length > 0)} />
    </section>

    <section className="content-band next-action">
      <SectionTitle title="下一步" />
      <p>{nextAction.description}</p>
      <Button icon={<nextAction.icon size={16} />} onClick={nextAction.onClick} type={nextAction.primary ? "primary" : "default"}>
        {nextAction.label}
      </Button>
    </section>

    <section className="content-band">
      <SectionTitle title="就绪状态" />
      <div className="metric-grid">{cards.map((card) => <MetricCard key={card.title} {...card} />)}</div>
    </section>

    <section className="content-band">
      <SectionTitle title="监控结果" />
      <Table columns={columns} dataSource={hitRows} locale={{ emptyText: "尚未命中目标车票" }} pagination={false} size="middle" />
    </section>

    <section className="content-band risk-panel">
      <SectionTitle title="风险控制" />
      <StatusBadge tone={riskTone}>{riskLabel[status.risk_level] ?? "需注意"}</StatusBadge>
      <p>{status.auto_submit_enabled || status.auto_alternate_enabled ? "已有危险自动化启用，请确认这是有意操作。" : "自动提交和候补排队保持关闭。"}</p>
    </section>
  </div>
);
```

Define `nextAction`, `cards`, `columns`, `hitRows`, and `riskTone` above render. Use `railwatchStore.getState().setActivePage("设置")`, `setActivePage("行程设置")`, or `setActivePage("监控")` for navigation actions.

- [ ] **Step 5: Add Dashboard CSS**

Add:

```css
.dispatch-dashboard {
  grid-template-columns: minmax(0, 1.45fr) minmax(280px, .55fr);
}

.dispatch-hero,
.dispatch-flow {
  grid-column: 1 / -1;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.next-action,
.risk-panel {
  align-content: start;
}
```

- [ ] **Step 6: Run Dashboard tests and verify they pass**

Run: `npm run test:renderer -- src/components/DashboardPage.test.tsx`

Expected: PASS.

- [ ] **Step 7: Commit Dashboard redesign**

```bash
git add src/components/DashboardPage.tsx src/components/DashboardPage.test.tsx src/styles.css
git commit -m "Redesign dashboard as dispatch overview"
```

## Task 4: Implement Option-3 Trip Setup

**Files:**
- Modify: `src/components/TripSetupPage.tsx`
- Modify: `src/components/TripSetupPage.test.tsx`
- Modify: `src/styles.css`

- [ ] **Step 1: Expand Trip Setup tests for independent quiet form layout**

Use this additional test:

```tsx
test("keeps trip setup as a form workspace without dashboard workflow", () => {
  const confirm = vi.fn(async () => false) as ConfirmDialog;
  const runCommand = vi.fn(async () => undefined) as CommandRunner;

  render(<TripSetupPage busy={null} confirm={confirm} runCommand={runCommand} />);

  expect(screen.getByRole("heading", { name: "行程设置" })).toBeTruthy();
  expect(screen.getByRole("heading", { name: "安全确认" })).toBeTruthy();
  expect(screen.getByLabelText("出发")).toBeTruthy();
  expect(screen.getByLabelText("到达")).toBeTruthy();
  expect(screen.getByText("自动提交关闭")).toBeTruthy();
  expect(screen.getByText("候补排队关闭")).toBeTruthy();
  expect(screen.queryByRole("list", { name: "监控流程" })).toBeNull();
});
```

- [ ] **Step 2: Run Trip Setup tests and verify they fail**

Run: `npm run test:renderer -- src/components/TripSetupPage.test.tsx`

Expected: FAIL because current page uses generic `路线`, `监控`, and `自动化` bands rather than the quiet safety layout.

- [ ] **Step 3: Replace Trip Setup structure with two-column safety form**

Use:

```tsx
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
      <RiskToggle checked={config.auto_submit} title={config.auto_submit ? "自动提交已启用" : "自动提交关闭"} description="发现车票后进入订单流程前必须确认" onChange={(checked) => void guardedAutomation("auto_submit", checked)} />
      <RiskToggle checked={config.auto_alternate} title={config.auto_alternate ? "候补排队已启用" : "候补排队关闭"} description="仅候补时排队前必须确认" onChange={(checked) => void guardedAutomation("auto_alternate", checked)} />
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
      <Button icon={<Search size={16} />} loading={busy === "analyzeQuery"} onClick={() => void runCommand("analyzeQuery", { config })} type="primary">
        分析
      </Button>
    </ActionRow>
  </div>
);
```

Define `monitorControls` as a fragment containing interval, passenger count, seat preference, prepare time, target time, timer, keep alive, and smart polling controls.

- [ ] **Step 4: Add Trip Setup CSS**

Add:

```css
.trip-setup-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, 420px);
  gap: 16px;
}

.trip-form-panel,
.trip-monitor-panel,
.trip-setup-grid .form-actions {
  grid-column: 1;
}

.safety-panel {
  display: grid;
  gap: 12px;
  align-content: start;
}
```

- [ ] **Step 5: Run Trip Setup tests and verify they pass**

Run: `npm run test:renderer -- src/components/TripSetupPage.test.tsx`

Expected: PASS.

- [ ] **Step 6: Commit Trip Setup redesign**

```bash
git add src/components/TripSetupPage.tsx src/components/TripSetupPage.test.tsx src/styles.css
git commit -m "Redesign trip setup as safety form"
```

## Task 5: Redesign Event Panel As Drawer Feed

**Files:**
- Modify: `src/components/EventPanel.tsx`
- Modify: `src/components/EventPanel.test.tsx`
- Modify: `src/App.tsx`
- Modify: `src/styles.css`

- [ ] **Step 1: Replace EventPanel tests with drawer-feed expectations**

Use the existing `EventPanel.test.tsx` content already present in the workspace. It expects:

```tsx
render(<EventPanel runCommand={runCommand} onClose={onClose} />);
expect(screen.getByRole("feed", { name: "事件流" })).toBeTruthy();
expect(screen.getByRole("button", { name: "隐藏事件面板" })).toBeTruthy();
expect(screen.getByText("当前显示 3 条")).toBeTruthy();
```

- [ ] **Step 2: Run EventPanel tests and verify they fail**

Run: `npm run test:renderer -- src/components/EventPanel.test.tsx`

Expected: FAIL because `EventPanel` does not accept `onClose`, does not sort errors first, and does not expose a feed role.

- [ ] **Step 3: Update EventPanel props and behavior**

Use:

```tsx
import { Eraser, FileDown, Pause, X } from "lucide-react";

export function EventPanel({ onClose, runCommand }: { onClose: () => void; runCommand: CommandRunner }) {
  const logs = useRailWatchStore((state) => state.logs);
  const errorCount = useRailWatchStore((state) => state.errorCount);
  const filteredLogs = useRailWatchStore((state) => state.filteredLogs);
  const logPaused = useRailWatchStore((state) => state.logPaused);
  const setLogPaused = useRailWatchStore((state) => state.setLogPaused);
  const clearLogs = useRailWatchStore((state) => state.clearLogs);
  const runtime = useRailWatchStore((state) => state.runtime);
  const [filter, setFilter] = useState("全部");
  const visibleLogs = [...filteredLogs(filter)].sort((a, b) => Number(b.level === "ERROR") - Number(a.level === "ERROR"));
  const exportLog = async () => {
    const defaultPath = runtime.data_dir ? `${runtime.data_dir}/railwatch-events.txt` : undefined;
    const path = await railwatchApi.showSaveDialog(defaultPath);
    if (path) {
      await runCommand("exportLog", { path }, "事件已导出");
    }
  };
  const clearBothLogs = async () => {
    clearLogs();
    await runCommand("clearLog");
  };
  const toolbarControls = (
    <>
      <Select
        value={filter}
        onChange={setFilter}
        options={["全部", "信息", "警告", "错误", "成功"].map((value) => ({ value, label: value }))}
        size="small"
        className="event-filter"
      />
      <Tooltip title={logPaused ? "恢复滚动" : "暂停滚动"}>
        <Button
          aria-label={logPaused ? "恢复滚动" : "暂停滚动"}
          aria-pressed={logPaused}
          icon={<Pause size={15} />}
          onClick={() => setLogPaused(!logPaused)}
          size="small"
          type={logPaused ? "primary" : "default"}
        />
      </Tooltip>
      <Tooltip title="清空事件">
        <Button aria-label="清空事件" icon={<Eraser size={15} />} onClick={() => void clearBothLogs()} size="small" />
      </Tooltip>
      <Tooltip title="导出事件">
        <Button aria-label="导出事件" icon={<FileDown size={15} />} onClick={() => void exportLog()} size="small" />
      </Tooltip>
    </>
  );

  return (
    <aside className="event-panel" aria-label="事件面板">
      <div className="event-head">
        <div>
          <h2>事件</h2>
          <span>当前显示 {visibleLogs.length} 条 · {errorCount()} 个错误</span>
          {logPaused ? <strong className="event-paused">事件流已暂停</strong> : null}
        </div>
        <Button aria-label="隐藏事件面板" icon={<X size={15} />} onClick={onClose} size="small" />
      </div>
      <div className="event-toolbar">{toolbarControls}</div>
      <div className={logPaused ? "event-list paused" : "event-list"} role="feed" aria-label="事件流">
        {visibleLogs.map((entry, index) => (
          <article className={`event-entry ${entry.level.toLowerCase()}`} key={`${entry.time}-${index}`}>
            <span>{entry.time}</span>
            <strong>{entry.level}</strong>
            <p>{entry.message}</p>
          </article>
        ))}
      </div>
    </aside>
  );
}
```

Define `toolbarControls` as the filter select, pause/resume button with `aria-pressed`, clear button, and export button.

- [ ] **Step 4: Wire close prop in App**

```tsx
eventPanel={eventPanelVisible ? <EventPanel runCommand={runCommand} onClose={() => setEventPanelVisible(false)} /> : null}
```

- [ ] **Step 5: Add EventPanel CSS**

Add:

```css
.event-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.event-paused {
  display: block;
  margin-top: 6px;
  color: var(--amber);
  font-size: 12px;
}

.event-entry {
  min-height: 64px;
}
```

- [ ] **Step 6: Run EventPanel tests and verify they pass**

Run: `npm run test:renderer -- src/components/EventPanel.test.tsx`

Expected: PASS.

- [ ] **Step 7: Commit event panel redesign**

```bash
git add src/components/EventPanel.tsx src/components/EventPanel.test.tsx src/App.tsx src/styles.css
git commit -m "Redesign event panel as drawer feed"
```

## Task 6: Polish Monitor And Settings Pages

**Files:**
- Modify: `src/components/MonitorPage.tsx`
- Modify: `src/components/MonitorPage.test.tsx`
- Modify: `src/components/SettingsPage.tsx`
- Modify: `src/components/SettingsPage.test.tsx`
- Modify: `src/styles.css`

- [ ] **Step 1: Update Settings test to match the approved spec**

Replace the current Settings test body with:

```tsx
test("shows appearance, local runtime data, and separated maintenance actions", () => {
  const runCommand = vi.fn(async () => undefined) as CommandRunner;
  const setDarkMode = vi.fn();

  render(<SettingsPage busy={null} darkMode={false} runCommand={runCommand} setDarkMode={setDarkMode} />);

  expect(screen.getByRole("heading", { name: "外观" })).toBeTruthy();
  expect(screen.getByText("暗色模式")).toBeTruthy();
  expect(screen.getByRole("heading", { name: "本地运行" })).toBeTruthy();
  expect(screen.getByText("C:/RailWatch/data")).toBeTruthy();
  expect(screen.getByRole("heading", { name: "维护操作" })).toBeTruthy();
  expect(screen.getByRole("button", { name: /清除数据/ })).toBeTruthy();
});
```

- [ ] **Step 2: Keep Monitor test focused on gated controls**

Use current `MonitorPage.test.tsx` and update the final active page expectation to `监控` when needed:

```tsx
activePage: "监控",
```

- [ ] **Step 3: Run Monitor and Settings tests and verify failures**

Run: `npm run test:renderer -- src/components/MonitorPage.test.tsx src/components/SettingsPage.test.tsx`

Expected: Settings FAIL because the current prop signature or headings are not aligned; Monitor PASS or fails only on page-name contract.

- [ ] **Step 4: Update MonitorPage layout**

Use:

```tsx
return (
  <div className="monitor-stack monitor-workspace">
    <section className="content-band monitor-control-band">
      <div className="monitor-header">
        <SectionTitle eyebrow="Live Monitor" title="购票监控" />
        <div className="button-row">
          <Button disabled={!status.query_ready || status.monitoring} icon={<Play size={16} />} loading={busy === "startMonitor"} onClick={() => void runCommand("startMonitor", { config })} type="primary">
            启动监控
          </Button>
          <Button danger disabled={!status.monitoring} icon={<Square size={16} />} loading={busy === "stopMonitor"} onClick={() => void runCommand("stopMonitor")}>
            停止监控
          </Button>
        </div>
      </div>
      <div className="inline-status">{status.summary}</div>
    </section>
    <section className="content-band">
      <SectionTitle title="查询结果" />
      <Table columns={columns} dataSource={results.map((row, index) => ({ ...row, key: `${row.train}-${index}` }))} locale={{ emptyText: "还没有查询结果" }} pagination={{ pageSize: 8, hideOnSinglePage: true }} size="middle" />
    </section>
  </div>
);
```

- [ ] **Step 5: Update SettingsPage signature and layout**

Make props include `darkMode` and `setDarkMode`:

```tsx
export function SettingsPage({
  busy,
  darkMode,
  runCommand,
  setDarkMode,
}: {
  busy: string | null;
  darkMode: boolean;
  runCommand: CommandRunner;
  setDarkMode: (value: boolean) => void;
}) {
  const runtime = useRailWatchStore((state) => state.runtime);
  const saveTheme = async (checked: boolean) => {
    setDarkMode(checked);
    await runCommand("savePreferences", { theme: checked ? "dark" : "light" });
  };
  const settingsButtons = (
    <>
      <Button icon={<Activity size={16} />} loading={busy === "checkEnvironment"} onClick={() => void runCommand("checkEnvironment")}>
        检查环境
      </Button>
      <Button icon={<Download size={16} />} loading={busy === "downloadChromeDriver"} onClick={() => void runCommand("downloadChromeDriver")} type="primary">
        下载 ChromeDriver
      </Button>
      <Button icon={<LogIn size={16} />} loading={busy === "openLogin"} onClick={() => void runCommand("openLogin")}>
        打开登录
      </Button>
      <Button danger icon={<XCircle size={16} />} loading={busy === "closeBrowser"} onClick={() => void runCommand("closeBrowser")}>
        关闭浏览器
      </Button>
      <Button danger icon={<Trash2 size={16} />} loading={busy === "clearLocalData"} onClick={() => void runCommand("clearLocalData")}>
        清除数据
      </Button>
    </>
  );
  return (
    <div className="settings-grid settings-workspace">
      <section className="content-band">
        <SectionTitle title="外观" />
        <div className="settings-row">
          <span>暗色模式</span>
          <Switch checked={darkMode} onChange={(checked) => void saveTheme(checked)} />
        </div>
      </section>
      <section className="content-band span-two">
        <SectionTitle title="本地运行" />
        <dl className="data-list">
          <dt>数据目录</dt>
          <dd>{runtime.data_dir}</dd>
          <dt>ChromeDriver</dt>
          <dd>{runtime.chromedriver_path}</dd>
          <dt>Chrome 版本</dt>
          <dd>{runtime.chrome_version}</dd>
        </dl>
      </section>
      <section className="content-band span-two danger-zone">
        <SectionTitle title="维护操作" />
        <div className="control-grid">{settingsButtons}</div>
      </section>
    </div>
  );
}
```

Define `settingsButtons` as the existing check environment, download ChromeDriver, open login, close browser, and clear data buttons.

- [ ] **Step 6: Run Monitor and Settings tests and verify they pass**

Run: `npm run test:renderer -- src/components/MonitorPage.test.tsx src/components/SettingsPage.test.tsx`

Expected: PASS.

- [ ] **Step 7: Commit monitor and settings polish**

```bash
git add src/components/MonitorPage.tsx src/components/MonitorPage.test.tsx src/components/SettingsPage.tsx src/components/SettingsPage.test.tsx src/styles.css
git commit -m "Polish monitor and settings pages"
```

## Task 7: Final Theme Pass

**Files:**
- Modify: `src/App.tsx`
- Modify: `src/main.tsx`
- Modify: `src/styles.css`

- [ ] **Step 1: Run renderer tests before theme edits**

Run: `npm run test:renderer`

Expected: PASS before CSS-only theme work begins.

- [ ] **Step 2: Remove duplicate provider drift**

Keep `RailWatchApp` as the owner of runtime theme tokens. In `src/main.tsx`, remove the outer `ConfigProvider` and render:

```tsx
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AntApp>
      <RailWatchApp />
    </AntApp>
  </React.StrictMode>,
);
```

- [ ] **Step 3: Extend Ant Design tokens in `src/App.tsx`**

Use:

```tsx
token: {
  colorPrimary: darkMode ? "#59d6b0" : "#0f8f62",
  colorBgBase: darkMode ? "#0d1117" : "#eef2f0",
  colorTextBase: darkMode ? "#eef4f1" : "#17201c",
  borderRadius: 8,
  fontFamily: '"Microsoft YaHei UI", "Noto Sans SC", "Segoe UI", sans-serif',
},
components: {
  Button: { controlHeight: 34, borderRadius: 8 },
  Input: { controlHeight: 34, borderRadius: 8 },
  Select: { controlHeight: 34, borderRadius: 8 },
  Table: { borderColor: darkMode ? "#25313d" : "#dce3df" },
},
```

- [ ] **Step 4: Replace root theme variables in `src/styles.css`**

Use this root token block:

```css
:root {
  --bg: #edf1f3;
  --bg-rail: #f7f9fa;
  --surface: #ffffff;
  --surface-muted: #f3f6f7;
  --surface-elevated: #ffffff;
  --text: #17201c;
  --muted: #65727a;
  --border: #d8e0e4;
  --green: #0f8f62;
  --blue: #2478c8;
  --indigo: #5567b1;
  --teal: #168f8a;
  --amber: #b66b00;
  --red: #c93636;
  --slate: #59656d;
  color: var(--text);
  background: var(--bg);
  font-family: "Microsoft YaHei UI", "Noto Sans SC", "Segoe UI", sans-serif;
}

.app-shell.dark {
  --bg: #0d1117;
  --bg-rail: #111821;
  --surface: #151c25;
  --surface-muted: #1b2530;
  --surface-elevated: #202b36;
  --text: #eef4f1;
  --muted: #9aa8b3;
  --border: #263441;
  --green: #59d68f;
  --blue: #73b7ff;
  --indigo: #a7b4ff;
  --teal: #66d7cc;
  --amber: #e2aa55;
  --red: #ff7b7b;
  --slate: #a8b2ba;
}
```

- [ ] **Step 5: Run typecheck and renderer tests**

Run: `npm run typecheck`

Expected: PASS.

Run: `npm run test:renderer`

Expected: PASS.

- [ ] **Step 6: Commit final theme pass**

```bash
git add src/App.tsx src/main.tsx src/styles.css
git commit -m "Apply macOS dark theme tokens"
```

## Task 8: Visual Verification And Cleanup

**Files:**
- Modify only if verification finds a visible issue: `src/styles.css` or the affected `src/components/*.tsx`.

- [ ] **Step 1: Start the renderer**

Run: `npm run dev:renderer -- --host 127.0.0.1 --port 5173`

Expected: Vite serves `http://127.0.0.1:5173`.

- [ ] **Step 2: Open the renderer in the in-app browser**

Open `http://127.0.0.1:5173`.

Expected: Dashboard renders with the dispatch overview. Because this is the renderer without Electron preload, Electron bridge error notifications can appear during dev preview; ignore bridge errors for visual layout checks.

- [ ] **Step 3: Verify page boundaries visually**

Check:

- Dashboard contains route summary, workflow, status metrics, hits, and risk panel.
- Dashboard does not show full fields for passenger, seat preference, alternate deadline, or target time.
- Trip Setup contains route fields, monitoring settings, safety review, save, and analyze.
- Trip Setup does not show the Dashboard workflow stepper.
- Event panel can be hidden and shown.
- Settings separates neutral maintenance actions from destructive actions.

- [ ] **Step 4: Fix visible layout defects**

Only adjust concrete defects found in Step 3. Examples of acceptable fixes:

```css
.metric-grid {
  grid-template-columns: repeat(3, minmax(180px, 1fr));
}

.event-panel {
  overflow: hidden;
}

.event-list {
  min-height: 0;
}
```

- [ ] **Step 5: Run final verification**

Run: `npm run typecheck`

Expected: PASS.

Run: `npm run test:renderer`

Expected: PASS.

Run: `npm run build:renderer`

Expected: Vite build completes and writes `dist/`.

- [ ] **Step 6: Commit visual cleanup**

```bash
git add src/App.tsx src/main.tsx src/styles.css src/components
git commit -m "Verify RailWatch UI redesign"
```

## Execution Notes

- Do not stage `.superpowers/` visual-companion files.
- Do not run `git reset --hard` or discard unrelated dirty files.
- Before each task, run `git status --short` and inspect any files touched by that task.
- If a file has unrelated user edits, preserve them and make the smallest compatible change.
- Stop after each task commit for review when using subagent-driven development.

## Completion Criteria

- `npm run typecheck` passes.
- `npm run test:renderer` passes.
- `npm run build:renderer` passes.
- Dashboard is visually and structurally the option-2 dispatch page.
- Trip Setup is visually and structurally the option-3 safety form page.
- The two pages remain independent and are not merged into one combined screen.
- Event panel controls still work: filter, pause/resume, clear, export, show/hide.
- Dangerous automation toggles still require confirmation before enabling.
