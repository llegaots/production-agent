"use client";

import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { tints } from "@/components/ui/tint";
import { hourLabel, isSameDay, timeLabel, timeToMinutes, minutesToHHMM, WEEKDAYS_SHORT, ymd } from "@/lib/calendar";
import type { Shift } from "@/lib/types";

const START_HOUR = 7;
const END_HOUR = 21;
const HOUR = 54;
const TOTAL = (END_HOUR - START_HOUR) * HOUR;
const hours = Array.from({ length: END_HOUR - START_HOUR + 1 }, (_, i) => START_HOUR + i);

function ShiftBlock({ shift }: { shift: Shift }) {
  const t = tints[shift.tint];
  const startMin = timeToMinutes(shift.start);
  const endMin = timeToMinutes(shift.end);
  const top = Math.max(0, ((startMin - START_HOUR * 60) / 60) * HOUR);
  const height = Math.max(26, ((endMin - startMin) / 60) * HOUR - 4);

  return (
    <div
      onClick={(e) => e.stopPropagation()}
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData("text/shift", shift.id);
        e.dataTransfer.effectAllowed = "move";
      }}
      style={{ top, height }}
      className="absolute left-1 right-1 z-10 cursor-grab active:cursor-grabbing"
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.96 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ type: "spring", stiffness: 320, damping: 26 }}
        className={cn(
          "relative h-full w-full overflow-hidden rounded-xl border px-2 py-1.5 shadow-soft",
          t.soft,
          "border-black/[0.04]",
        )}
      >
        <div className={cn("absolute inset-y-1 left-0 w-1 rounded-full", t.solid)} />
        <div className="pl-1.5">
          <div className="truncate text-[11px] font-bold text-ink">{shift.repName}</div>
          <div className="truncate text-[10px] text-ink-soft">
            {timeLabel(shift.start)}-{timeLabel(shift.end)}
          </div>
          {height > 52 && <div className="mt-0.5 truncate text-[10px] text-muted">{shift.territory}</div>}
        </div>
      </motion.div>
    </div>
  );
}

export function WeekGrid({
  days,
  shifts,
  now,
  onCreateOnDay,
  onMoveShift,
}: {
  days: Date[];
  shifts: Shift[];
  now: Date | null;
  onCreateOnDay: (day: Date) => void;
  onMoveShift: (id: string, date: string, start?: string) => void;
}) {
  const nowMin = now ? now.getHours() * 60 + now.getMinutes() : 0;
  const nowTop = ((nowMin - START_HOUR * 60) / 60) * HOUR;
  const nowVisible = now && nowMin >= START_HOUR * 60 && nowMin <= END_HOUR * 60;

  return (
    <div className="overflow-hidden rounded-3xl border border-line bg-surface shadow-card">
      {/* day headers */}
      <div className="flex border-b border-line bg-surface-muted/50">
        <div className="w-14 shrink-0" />
        <div className="grid flex-1 grid-cols-7">
          {days.map((day) => {
            const today = now ? isSameDay(day, now) : false;
            return (
              <div key={day.toISOString()} className="border-l border-line px-2 py-2.5 text-center">
                <div className="text-[11px] font-medium uppercase tracking-wide text-faint">
                  {WEEKDAYS_SHORT[day.getDay()]}
                </div>
                <div
                  className={cn(
                    "mx-auto mt-0.5 grid size-7 place-items-center rounded-full text-sm font-bold",
                    today ? "bg-primary text-white" : "text-ink",
                  )}
                >
                  {day.getDate()}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* time grid */}
      <div className="flex max-h-[620px] overflow-y-auto pretty-scroll">
        {/* hour gutter */}
        <div className="w-14 shrink-0">
          <div className="relative" style={{ height: TOTAL }}>
            {hours.map((h, i) => (
              <div
                key={h}
                className="absolute right-2 -translate-y-1/2 text-[10px] font-medium text-faint"
                style={{ top: i * HOUR }}
              >
                {i === 0 ? "" : hourLabel(h)}
              </div>
            ))}
          </div>
        </div>

        {/* day columns */}
        <div className="grid flex-1 grid-cols-7">
          {days.map((day) => {
            const dayShifts = shifts.filter((s) => s.date === ymd(day));
            const today = now ? isSameDay(day, now) : false;
            return (
              <div
                key={day.toISOString()}
                onClick={() => onCreateOnDay(day)}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  const id = e.dataTransfer.getData("text/shift");
                  if (!id) return;
                  const rect = e.currentTarget.getBoundingClientRect();
                  const y = e.clientY - rect.top;
                  let mins = START_HOUR * 60 + (y / HOUR) * 60;
                  mins = Math.round(mins / 15) * 15;
                  mins = Math.max(START_HOUR * 60, Math.min((END_HOUR - 0.5) * 60, mins));
                  onMoveShift(id, ymd(day), minutesToHHMM(mins));
                }}
                className="group relative border-l border-line transition-colors hover:bg-surface-muted/40"
                style={{ height: TOTAL }}
              >
                {hours.map((h, i) => (
                  <div
                    key={h}
                    className="absolute inset-x-0 border-t border-line-soft"
                    style={{ top: i * HOUR }}
                  />
                ))}

                {today && nowVisible && (
                  <div className="absolute inset-x-0 z-20" style={{ top: nowTop }}>
                    <div className="relative h-px bg-primary">
                      <span className="absolute -left-1 -top-1 size-2 rounded-full bg-primary" />
                    </div>
                  </div>
                )}

                {dayShifts.map((s) => (
                  <ShiftBlock key={s.id} shift={s} />
                ))}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
