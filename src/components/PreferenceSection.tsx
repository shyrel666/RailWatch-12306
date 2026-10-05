import { useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";

export function PreferenceSection({
  id,
  title,
  description,
  defaultOpen = false,
  children,
}: {
  id: string;
  title: string;
  description: string;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <details
      className="preference-section"
      id={id}
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>
        <div>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
        <ChevronDown size={16} />
      </summary>
      <div className="preference-body">{children}</div>
    </details>
  );
}
