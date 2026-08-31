import type { CSSProperties } from "react";
import { Link } from "react-router-dom";

export type EmptyStateIcon = "data" | "experiments" | "research" | "resources" | "autonomy";

interface Props {
  icon: EmptyStateIcon;
  title: string;
  description: string;
  actionLabel?: string;
}

const ACCENTS: Record<EmptyStateIcon, string> = {
  data: "var(--group-data-b)",
  experiments: "var(--group-code-b)",
  research: "var(--group-research-b)",
  resources: "var(--group-train-b)",
  autonomy: "var(--primary)",
};
function EmptyIcon({ icon }: { icon: EmptyStateIcon }) {
  if (icon === "data") {
    return (
      <svg viewBox="0 0 64 64" fill="none">
        <ellipse cx="32" cy="17" rx="18" ry="8" stroke="currentColor" strokeWidth="2.5" />
        <path d="M14 17v15c0 4.4 8.1 8 18 8s18-3.6 18-8V17M14 32v15c0 4.4 8.1 8 18 8s18-3.6 18-8V32" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
        <path d="m25 31 5 5 10-11" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  if (icon === "experiments") {
    return (
      <svg viewBox="0 0 64 64" fill="none">
        <path d="M24 10h16M28 10v13L16.5 47.4A5 5 0 0 0 21 54.5h22a5 5 0 0 0 4.5-7.1L36 23V10" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M21 42h22M25 35l5 3 7-7 5 4" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  if (icon === "research") {
    return (
      <svg viewBox="0 0 64 64" fill="none">
        <path d="M12 16.5c8.6-2.8 15.3-.8 20 4.5v31c-4.7-5.3-11.4-7.3-20-4.5v-31ZM52 16.5c-8.6-2.8-15.3-.8-20 4.5v31c4.7-5.3 11.4-7.3 20-4.5v-31Z" stroke="currentColor" strokeWidth="2.5" strokeLinejoin="round" />
        <circle cx="43" cy="30" r="6" stroke="currentColor" strokeWidth="2.5" />
        <path d="m47.5 34.5 5 5" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
      </svg>
    );
  }
  if (icon === "resources") {
    return (
      <svg viewBox="0 0 64 64" fill="none">
        <path d="M12 50h40M17 43V31h8v12M28 43V20h8v23M39 43V12h8v31" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
        <path d="m16 24 11-8 9 2 12-9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 64 64" fill="none">
      <circle cx="32" cy="32" r="21" stroke="currentColor" strokeWidth="2.5" />
      <path d="M32 19v14l9 6M17 12l-5 5M47 12l5 5" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M24 53h16" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  );
}

export function RouteEmptyState({ icon, title, description, actionLabel = "Open Live Workflow" }: Props) {
  return (
    <section className="route-empty-state" style={{ "--empty-accent": ACCENTS[icon] } as CSSProperties}>
      <div className="route-empty-state__glass" aria-hidden="true">
        <div className="route-empty-state__icon">
          <EmptyIcon icon={icon} />
        </div>
      </div>
      <div className="route-empty-state__copy">
        <h2>{title}</h2>
        <p>{description}</p>
      </div>
      <Link to="/" className="route-empty-state__action">
        {actionLabel}
        <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <path d="M3 8h9M9 4.5 12.5 8 9 11.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </Link>
    </section>
  );
}
