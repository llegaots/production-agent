"use client";

import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Plus, CalendarRange, Info } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/segmented";
import { WeekGrid } from "./week-grid";
import { MonthGrid } from "./month-grid";
import { CreateShiftDrawer } from "./create-shift-drawer";
import {
  addDays,
  addMonths,
  monthLabel,
  weekDays,
  weekRangeLabel,
  ymd,
  timeToMinutes,
  minutesToHHMM,
} from "@/lib/calendar";
import type { Rep, Route, Shift } from "@/lib/types";

type View = "week" | "month";

export function ScheduleView({
  initialShifts,
  reps,
  routes,
}: {
  initialShifts: Shift[];
  reps: Rep[];
  routes: Route[];
}) {
  const [view, setView] = useState<View>("week");
  const [cursor, setCursor] = useState<Date>(() => new Date());
  const [shifts, setShifts] = useState<Shift[]>(initialShifts);
  const [now, setNow] = useState<Date | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [createDate, setCreateDate] = useState<string>(() => ymd(new Date()));

  // set after mount → keeps SSR/CSR markup identical (no "today" flash mismatch)
  useEffect(() => {
    setNow(new Date());
    const t = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(t);
  }, []);

  const days = weekDays(cursor);
  const label = view === "week" ? weekRangeLabel(days) : monthLabel(cursor);

  const periodShifts =
    view === "week"
      ? shifts.filter((s) => days.some((d) => ymd(d) === s.date))
      : shifts.filter((s) => {
          const [y, m] = s.date.split("-").map(Number);
          return y === cursor.getFullYear() && m === cursor.getMonth() + 1;
        });

  const go = (dir: -1 | 1) =>
    setCursor((c) => (view === "week" ? addDays(c, dir * 7) : addMonths(c, dir)));

  const openCreate = (day: Date) => {
    setCreateDate(ymd(day));
    setCreateOpen(true);
  };

  const addShift = async (shift: Shift) => {
    const tempId = shift.id;
    setShifts((prev) => [...prev, shift]); // optimistic
    try {
      const res = await fetch("/api/shifts", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          marketer_id: shift.repId || null,
          date: shift.date,
          start: shift.start,
          end: shift.end,
          notes: shift.notes,
        }),
      });
      const j = await res.json();
      if (res.ok && j.id) setShifts((prev) => prev.map((s) => (s.id === tempId ? { ...s, id: j.id } : s)));
    } catch {
      /* keep optimistic shift this session even if persist fails */
    }
  };

  // drag-and-drop reschedule: change a shift's date (and optional start time)
  const moveShift = (id: string, date: string, newStart?: string) => {
    let patch: { date: string; start: string; end: string } | null = null;
    setShifts((prev) =>
      prev.map((s) => {
        if (s.id !== id) return s;
        let start = s.start;
        let end = s.end;
        if (newStart) {
          const dur = Math.max(30, timeToMinutes(s.end) - timeToMinutes(s.start));
          start = newStart;
          end = minutesToHHMM(timeToMinutes(newStart) + dur);
        }
        patch = { date, start, end };
        return { ...s, date, start, end };
      }),
    );
    if (patch && !id.startsWith("local-")) {
      fetch(`/api/shifts/${id}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(patch),
      }).catch(() => {});
    }
  };

  return (
    <div className="mx-auto flex max-w-[1500px] flex-col gap-4">
      {/* toolbar */}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1">
            <button
              onClick={() => go(-1)}
              className="grid size-9 place-items-center rounded-xl border border-line bg-surface text-muted shadow-soft transition-colors hover:bg-surface-muted hover:text-ink"
            >
              <ChevronLeft className="size-4.5" />
            </button>
            <button
              onClick={() => setCursor(new Date())}
              className="h-9 rounded-xl border border-line bg-surface px-3 text-[13px] font-medium text-ink-soft shadow-soft transition-colors hover:bg-surface-muted"
            >
              Today
            </button>
            <button
              onClick={() => go(1)}
              className="grid size-9 place-items-center rounded-xl border border-line bg-surface text-muted shadow-soft transition-colors hover:bg-surface-muted hover:text-ink"
            >
              <ChevronRight className="size-4.5" />
            </button>
          </div>
          <div>
            <h2 className="font-display text-lg font-extrabold tracking-tight text-ink">{label}</h2>
            <p className="text-[12px] text-muted">
              {periodShifts.length} shift{periodShifts.length === 1 ? "" : "s"} this {view}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Segmented
            size="sm"
            value={view}
            onChange={setView}
            options={[
              { value: "week", label: "Week" },
              { value: "month", label: "Month" },
            ]}
          />
          <Button size="sm" onClick={() => openCreate(cursor)}>
            <Plus className="size-4" /> New shift
          </Button>
        </div>
      </div>

      {shifts.length === 0 && (
        <div className="flex items-center gap-2.5 rounded-2xl border border-primary-100 bg-primary-50/50 px-4 py-2.5">
          <Info className="size-4 shrink-0 text-primary-600" />
          <p className="text-[12.5px] text-ink-soft">
            No shifts scheduled yet - click any day, or hit <span className="font-semibold">New shift</span>, to plan one.
          </p>
        </div>
      )}

      {view === "week" ? (
        <WeekGrid days={days} shifts={shifts} now={now} onCreateOnDay={openCreate} onMoveShift={moveShift} />
      ) : (
        <MonthGrid cursor={cursor} shifts={shifts} now={now} onCreateOnDay={openCreate} onMoveShift={moveShift} />
      )}

      <div className="flex items-center gap-2 px-1 text-[12px] text-muted">
        <CalendarRange className="size-3.5" />
        Tip: shift colours match the assigned rep.
      </div>

      <CreateShiftDrawer
        open={createOpen}
        onOpenChange={setCreateOpen}
        reps={reps}
        routes={routes}
        defaultDate={createDate}
        onCreate={addShift}
      />
    </div>
  );
}
