import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

// Every settings card shares one header (icon, title, summary, actions) and one
// row anatomy (icon, copy, control) so the page reads as a single system.
export function SettingsSection({
  id,
  icon: Icon,
  title,
  description,
  actions,
  className,
  focusable = false,
  children,
}: {
  id: string;
  icon: LucideIcon;
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
  focusable?: boolean;
  children?: ReactNode;
}) {
  return (
    <section className={"settings-section" + (className ? " " + className : "")} id={id} tabIndex={focusable ? -1 : undefined}>
      <header className="settings-section-head">
        <span className="settings-section-icon" aria-hidden="true"><Icon size={17} /></span>
        <div className="section-title-copy">
          <h2>{title}</h2>
          {description && <p>{description}</p>}
        </div>
        {actions && <div className="settings-section-actions">{actions}</div>}
      </header>
      {children && <div className="settings-section-body">{children}</div>}
    </section>
  );
}

export function SettingRow({
  id,
  icon: Icon,
  title,
  children,
  control,
  tone,
}: {
  id?: string;
  icon: LucideIcon;
  title: ReactNode;
  children?: ReactNode;
  control: ReactNode;
  tone?: "danger";
}) {
  return (
    <div className={"setting-row" + (tone === "danger" ? " danger-zone" : "")} id={id} tabIndex={id ? -1 : undefined}>
      <span className="setting-icon" aria-hidden="true"><Icon size={16} /></span>
      <div className="setting-copy">
        <strong>{title}</strong>
        {children}
      </div>
      <div className="setting-control">{control}</div>
    </div>
  );
}
