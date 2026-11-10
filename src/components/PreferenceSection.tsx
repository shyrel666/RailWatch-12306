import { useState, type ReactNode } from "react";
import { ChevronDown, type LucideIcon } from "lucide-react";

export function PreferenceSection({
  id,
  title,
  description,
  icon: Icon,
  active = false,
  defaultOpen = false,
  children,
}: {
  id: string;
  title: string;
  description?: string;
  icon?: LucideIcon;
  active?: boolean;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <details
      className={`preference-section${active ? " is-active" : ""}`}
      id={id}
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>
        {Icon ? (
          <span className="section-icon-badge" aria-hidden="true">
            <Icon size={16} />
          </span>
        ) : null}
        <div className="preference-heading">
          <h2>{title}</h2>
          {description ? <p>{description}</p> : null}
        </div>
        <ChevronDown size={16} />
      </summary>
      <div className="preference-body">{children}</div>
    </details>
  );
}
