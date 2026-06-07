import { Children, cloneElement, isValidElement } from "react";
import type { ReactElement, ReactNode } from "react";

const labelableTags = new Set(["button", "input", "meter", "output", "progress", "select", "textarea"]);

function withFieldLabel(children: ReactNode, label: string) {
  return Children.map(children, (child) => {
    if (isValidElement(child) && typeof child.type === "string" && labelableTags.has(child.type)) {
      const props = child.props as { "aria-label"?: string; id?: string };
      if (!props["aria-label"] && !props.id) {
        return cloneElement(child as ReactElement<Record<string, unknown>>, { "aria-label": label });
      }
    }

    return child;
  });
}

export function Field({ children, description, label }: { children: ReactNode; description?: string; label: string }) {
  return (
    <label className="field">
      <span>{label}</span>
      {withFieldLabel(children, label)}
      {description ? <small aria-hidden="true">{description}</small> : null}
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
