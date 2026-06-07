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
