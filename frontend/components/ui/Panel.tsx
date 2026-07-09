import type { ReactNode } from "react";

interface PanelProps {
  title: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}

/** Framed terminal panel with an uppercase eyebrow header. */
export default function Panel({
  title,
  right,
  children,
  className = "",
  bodyClassName = "",
}: PanelProps) {
  return (
    <section
      className={`flex min-h-0 flex-col overflow-hidden rounded-lg border border-border bg-panel ${className}`}
    >
      <header className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
        <div className="flex items-center gap-2">
          <span className="h-3 w-[3px] rounded-full bg-accent" />
          <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
            {title}
          </h2>
        </div>
        {right}
      </header>
      <div className={`min-h-0 flex-1 ${bodyClassName}`}>{children}</div>
    </section>
  );
}
