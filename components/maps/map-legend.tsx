import { cn } from "@/lib/utils";
import type { DoorOutcome } from "@/lib/types";
import { OUTCOME_ORDER, outcomeColor, outcomeLabel } from "./outcome";

/** Small colour key for the door-outcome pins. Optionally shows per-outcome
 *  counts when a tally is provided. */
export function MapLegend({
  counts,
  className,
}: {
  counts?: Partial<Record<DoorOutcome, number>>;
  className?: string;
}) {
  const shown = counts ? OUTCOME_ORDER.filter((o) => (counts[o] ?? 0) > 0) : OUTCOME_ORDER;
  const list = shown.length ? shown : OUTCOME_ORDER;
  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-full border border-line bg-surface/90 px-3 py-1.5 text-[11px] font-medium text-ink shadow-soft backdrop-blur",
        className,
      )}
    >
      {list.map((o) => (
        <span key={o} className="inline-flex items-center gap-1.5">
          <span
            className="size-2.5 rounded-full ring-1 ring-inset ring-black/10"
            style={{ backgroundColor: outcomeColor[o] }}
          />
          {outcomeLabel[o]}
          {counts ? <span className="tabular-nums text-muted">{counts[o] ?? 0}</span> : null}
        </span>
      ))}
    </div>
  );
}
