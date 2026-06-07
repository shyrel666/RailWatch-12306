import { Children, cloneElement, isValidElement, useId } from "react";
import type { ReactElement, ReactNode } from "react";

const labelableTags = new Set(["button", "input", "meter", "output", "progress", "select", "textarea"]);

function mergeDescribedBy(existing: string | undefined, descriptionId: string | undefined) {
  if (!descriptionId) {
    return existing;
  }

  const ids = existing?.trim() ? existing.trim().split(/\s+/) : [];
  if (!ids.includes(descriptionId)) {
    ids.push(descriptionId);
  }

  return ids.join(" ");
}

function withFieldLabel(children: ReactNode, label: string, descriptionId?: string) {
  return Children.map(children, (child) => {
    if (isValidElement(child) && typeof child.type === "string" && labelableTags.has(child.type)) {
      const props = child.props as { "aria-describedby"?: string; "aria-label"?: string; id?: string };
      const nextProps: { "aria-describedby"?: string; "aria-label"?: string } = {};

      if (!props["aria-label"] && !props.id) {
        nextProps["aria-label"] = label;
      }

      const describedBy = mergeDescribedBy(props["aria-describedby"], descriptionId);
      if (describedBy && describedBy !== props["aria-describedby"]) {
        nextProps["aria-describedby"] = describedBy;
      }

      if (Object.keys(nextProps).length > 0) {
        return cloneElement(child as ReactElement<Record<string, unknown>>, nextProps);
      }
    }

    return child;
  });
}

export function Field({ children, description, label }: { children: ReactNode; description?: string; label: string }) {
  const generatedDescriptionId = useId();
  const descriptionId = description ? generatedDescriptionId : undefined;

  return (
    <label className="field">
      <span>{label}</span>
      {withFieldLabel(children, label, descriptionId)}
      {description ? <small id={descriptionId}>{description}</small> : null}
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
