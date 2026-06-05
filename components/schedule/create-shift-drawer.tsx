"use client";

import { useEffect, useState } from "react";
import { Check, CalendarPlus } from "lucide-react";
import { Drawer } from "@/components/ui/drawer";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Avatar } from "@/components/ui/avatar";
import { cn } from "@/lib/utils";
import { timeToMinutes } from "@/lib/calendar";
import type { AccentTint, Rep, Route, Shift } from "@/lib/types";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[12px] font-medium text-ink-soft">{label}</span>
      {children}
    </label>
  );
}

export function CreateShiftDrawer({
  open,
  onOpenChange,
  reps,
  routes,
  defaultDate,
  onCreate,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  reps: Rep[];
  routes: Route[];
  defaultDate: string;
  onCreate: (shift: Shift) => void;
}) {
  const [date, setDate] = useState(defaultDate);
  const [start, setStart] = useState("09:00");
  const [end, setEnd] = useState("13:00");
  const [repId, setRepId] = useState<string | null>(null);
  const [territory, setTerritory] = useState("");
  const [notes, setNotes] = useState("");

  useEffect(() => {
    if (open) setDate(defaultDate);
  }, [open, defaultDate]);

  const valid = date && timeToMinutes(end) > timeToMinutes(start);

  const submit = () => {
    if (!valid) return;
    const rep = reps.find((r) => r.id === repId);
    const tint: AccentTint = rep?.avatarTint ?? "emerald";
    onCreate({
      id: `local-${Date.now()}`,
      repId: rep?.id ?? "",
      repName: rep?.name ?? "Unassigned",
      tint,
      territory: territory || rep?.territory || "Unassigned",
      date,
      start,
      end,
      status: "scheduled",
      notes: notes || undefined,
    });
    setRepId(null);
    setTerritory("");
    setNotes("");
    onOpenChange(false);
  };

  return (
    <Drawer
      open={open}
      onOpenChange={onOpenChange}
      title="Schedule a shift"
      description="Assign a rep to a date, time and territory"
      widthClass="max-w-md"
    >
      <div className="flex flex-col gap-5 p-6">
        <Field label="Date">
          <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Start">
            <Input type="time" value={start} onChange={(e) => setStart(e.target.value)} />
          </Field>
          <Field label="End">
            <Input type="time" value={end} onChange={(e) => setEnd(e.target.value)} />
          </Field>
        </div>
        {date && timeToMinutes(end) <= timeToMinutes(start) && (
          <p className="-mt-2 text-[12px] text-[#be123c]">End time must be after start time.</p>
        )}

        <Field label="Territory">
          <Input
            value={territory}
            onChange={(e) => setTerritory(e.target.value)}
            placeholder="e.g. Leslieville"
            list="route-territories"
          />
          <datalist id="route-territories">
            {routes.map((r) => (
              <option key={r.id} value={r.territory} />
            ))}
          </datalist>
        </Field>

        <div>
          <span className="mb-2 block text-[12px] font-medium text-ink-soft">Assign rep</span>
          {reps.length === 0 && (
            <p className="rounded-2xl border border-dashed border-line bg-surface-muted/60 px-3 py-3 text-[12px] text-muted">
              No reps yet - you can still schedule an unassigned shift, or invite marketers in Settings.
            </p>
          )}
          <div className="flex flex-col gap-1.5">
            {reps.map((rep) => {
              const active = repId === rep.id;
              return (
                <button
                  key={rep.id}
                  onClick={() => setRepId(active ? null : rep.id)}
                  className={cn(
                    "flex items-center gap-3 rounded-2xl border px-3 py-2.5 text-left transition-colors",
                    active ? "border-primary-200 bg-primary-50" : "border-line hover:bg-surface-muted",
                  )}
                >
                  <Avatar name={rep.name} tint={rep.avatarTint} size="sm" status={rep.status} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[13px] font-semibold text-ink">{rep.name}</div>
                    <div className="truncate text-[11px] text-muted">{rep.territory}</div>
                  </div>
                  {active && <Check className="size-4 text-primary-600" />}
                </button>
              );
            })}
          </div>
        </div>

        <Field label="Notes">
          <Textarea
            rows={3}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Optional briefing for the rep…"
          />
        </Field>

        <div className="flex gap-2 pt-1">
          <Button variant="primary" className="flex-1" onClick={submit} disabled={!valid}>
            <CalendarPlus className="size-4" /> Schedule shift
          </Button>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
        </div>
      </div>
    </Drawer>
  );
}
