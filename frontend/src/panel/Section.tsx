import type { ReactNode } from "react";

/**
 * One collapsible block of the side panel.
 *
 * The panel grew to eight stacked sections in one scrolling column, where
 * nothing read as more important than anything else and the thing you wanted
 * was usually below the fold. Native `<details>` rather than a hand-rolled
 * accordion: it collapses without JavaScript, it is keyboard-operable and
 * screen-reader-legible for free, and browser find-in-page opens it.
 */
export default function Section({
  title,
  badge,
  defaultOpen = true,
  children,
}: {
  title: string;
  /** Short right-aligned count or status, e.g. "18" or "flagged". */
  badge?: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  return (
    <details className="section" open={defaultOpen}>
      <summary>
        <span className="section-title">{title}</span>
        {badge != null && <span className="section-badge mono-sm">{badge}</span>}
      </summary>
      <div className="section-body">{children}</div>
    </details>
  );
}
