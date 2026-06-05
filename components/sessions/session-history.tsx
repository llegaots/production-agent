import Link from "next/link";
import { Clock, Sparkles, ChevronRight, History } from "lucide-react";
import { Avatar } from "@/components/ui/avatar";
import { formatDuration, gradeLetter, timeAgo } from "@/lib/utils";
import type { Session } from "@/lib/types";

function durationMin(s: Session): number {
  if (!s.endedAt) return 0;
  return (new Date(s.endedAt).getTime() - new Date(s.startedAt).getTime()) / 60000;
}

/** Past sessions grouped per marketer. Each row links to the session detail page,
 *  where the full transcript (and, once Phase 3 lands, the grading) is available. */
export function SessionHistory({ sessions }: { sessions: Session[] }) {
  if (!sessions.length) return null;

  const groups = new Map<string, { repName: string; items: Session[] }>();
  for (const s of sessions) {
    const g = groups.get(s.repId) ?? { repName: s.repName, items: [] };
    g.items.push(s);
    groups.set(s.repId, g);
  }

  return (
    <div className="flex flex-col gap-3">
      <h3 className="flex items-center gap-2 px-1 text-sm font-semibold text-ink-soft">
        <History className="size-4" /> Session history · by marketer
      </h3>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {[...groups.entries()].map(([repId, g]) => (
          <div key={repId} className="rounded-3xl border border-line bg-surface p-4 shadow-card">
            <div className="mb-3 flex items-center gap-3">
              <Avatar name={g.repName} size="md" />
              <div>
                <p className="font-semibold text-ink">{g.repName}</p>
                <p className="text-[12px] text-muted">
                  {g.items.length} session{g.items.length === 1 ? "" : "s"}
                </p>
              </div>
            </div>
            <ul className="flex flex-col divide-y divide-line/70">
              {g.items.map((s) => (
                <li key={s.id}>
                  <Link
                    href={`/sessions/${s.id}`}
                    className="group flex items-center gap-3 py-2.5 transition-colors hover:bg-surface-muted/60"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[13px] font-medium text-ink">
                        {s.territory || "Field session"}
                      </p>
                      <p className="text-[12px] text-muted">{timeAgo(s.startedAt)}</p>
                    </div>
                    <span className="hidden items-center gap-1 text-[12px] text-muted sm:inline-flex">
                      <Clock className="size-3.5" />
                      {s.endedAt ? formatDuration(durationMin(s)) : "—"}
                    </span>
                    <span className="inline-flex items-center gap-1 text-[12px] text-muted">
                      <Sparkles className="size-3.5" />
                      {s.leads}
                    </span>
                    <span className="grid size-7 place-items-center rounded-lg bg-canvas-deep text-[12px] font-bold text-ink">
                      {s.grade ? gradeLetter(s.grade) : "–"}
                    </span>
                    <ChevronRight className="size-4 text-faint transition-transform group-hover:translate-x-0.5" />
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}
