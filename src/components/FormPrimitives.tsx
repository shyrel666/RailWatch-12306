import type { ReactNode } from "react";

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}

export function SectionTitle({ title }: { title: string }) {
  return (
    <div className="section-title">
      <h2>{title}</h2>
    </div>
  );
}
