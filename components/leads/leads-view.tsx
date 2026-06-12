"use client";

import { useMemo, useState } from "react";
import { Search, Plus, Table2, Columns3, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/segmented";
import { LeadsTable } from "./leads-table";
import { LeadsKanban } from "./leads-kanban";
import { LeadDrawer } from "./lead-drawer";
import { AddLeadDrawer } from "./add-lead-drawer";
import { cn } from "@/lib/utils";
import type { Lead, LeadStatus, Rep } from "@/lib/types";

type View = "table" | "board";
type Filter = "all" | LeadStatus | "needs-check";

/** Fully-automatic captures we are not yet sure of: not rooftop and not confirmed. */
const needsCheck = (l: Lead) => !l.addressVerified && l.addressConfidence !== "rooftop";

const filters: { value: Filter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "new", label: "New" },
  { value: "qualified", label: "Qualified" },
  { value: "callback", label: "Callback" },
  { value: "appointment", label: "Appointment" },
  { value: "won", label: "Won" },
  { value: "lost", label: "Lost" },
];

export function LeadsView({
  leads,
  reps,
  teamId,
}: {
  leads: Lead[];
  reps: Rep[];
  teamId: string | null;
}) {
  const [view, setView] = useState<View>("table");
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Lead | null>(null);
  const [open, setOpen] = useState(false);
  const [addOpen, setAddOpen] = useState(false);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return leads.filter((l) => {
      if (filter === "needs-check") {
        if (!needsCheck(l)) return false;
      } else if (filter !== "all" && l.status !== filter) {
        return false;
      }
      if (!q) return true;
      return (
        l.name.toLowerCase().includes(q) ||
        l.address.toLowerCase().includes(q) ||
        l.repName.toLowerCase().includes(q)
      );
    });
  }, [leads, filter, query]);

  const select = (lead: Lead) => {
    setSelected(lead);
    setOpen(true);
  };

  return (
    <div className="mx-auto flex max-w-[1400px] flex-col gap-4">
      {/* toolbar */}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap items-center gap-1.5">
          {filters.map((f) => {
            const count = f.value === "all" ? leads.length : leads.filter((l) => l.status === f.value).length;
            const active = filter === f.value;
            return (
              <button
                key={f.value}
                onClick={() => setFilter(f.value)}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[13px] font-medium transition-colors",
                  active
                    ? "bg-ink text-white"
                    : "border border-line bg-surface text-ink-soft hover:bg-surface-muted",
                )}
              >
                {f.label}
                <span
                  className={cn(
                    "nums rounded-full px-1.5 text-[11px] font-bold",
                    active ? "bg-white/20" : "bg-canvas-deep text-muted",
                  )}
                >
                  {count}
                </span>
              </button>
            );
          })}
          {(() => {
            const n = leads.filter(needsCheck).length;
            if (!n) return null;
            const active = filter === "needs-check";
            return (
              <button
                onClick={() => setFilter("needs-check")}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[13px] font-medium transition-colors",
                  active
                    ? "bg-[#be123c] text-white"
                    : "border border-rose-200 bg-rose-50 text-[#be123c] hover:bg-rose-100",
                )}
              >
                <AlertTriangle className="size-3.5" /> Needs address check
                <span
                  className={cn(
                    "nums rounded-full px-1.5 text-[11px] font-bold",
                    active ? "bg-white/20" : "bg-white text-[#be123c]",
                  )}
                >
                  {n}
                </span>
              </button>
            );
          })()}
        </div>

        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-faint" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search leads…"
              className="h-9 w-44 rounded-xl border border-line bg-surface pl-9 pr-3 text-sm text-ink placeholder:text-faint shadow-soft outline-none transition-all focus:w-56 focus:border-primary-200 focus:ring-2 focus:ring-primary/15"
            />
          </div>
          <Segmented
            size="sm"
            value={view}
            onChange={setView}
            options={[
              { value: "table", label: <Table2 className="size-4" /> },
              { value: "board", label: <Columns3 className="size-4" /> },
            ]}
          />
          <Button size="sm" onClick={() => setAddOpen(true)}>
            <Plus className="size-4" /> Add lead
          </Button>
        </div>
      </div>

      {view === "table" ? (
        <LeadsTable leads={filtered} onSelect={select} />
      ) : (
        <LeadsKanban leads={filtered} onSelect={select} />
      )}

      <LeadDrawer lead={selected} open={open} onOpenChange={setOpen} />
      <AddLeadDrawer open={addOpen} onOpenChange={setAddOpen} reps={reps} teamId={teamId} />
    </div>
  );
}
