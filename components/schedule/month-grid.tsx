"use client";

import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { tints } from "@/components/ui/tint";
import { isSameDay, monthMatrix, timeLabel, WEEKDAYS_SHORT, ymd } from "@/lib/calendar";
import type { Shift } from "@/lib/types";

function Chip({ shift }: { shift: Shift }) {
  const t = tints[shift.tint];
  return (
    <div
      onClick={(e) => e.stopPropagation()}
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData("text/shift", shift.id);
        e.dataTransfer.effectAllowed = "move";
      }}
      className={cn(
        "flex items-center gap-1 truncate rounded-md px-1.5 py-0.5 text-[10px] font-medium cursor-grab active:cursor-grabbing",
        t.soft,
      )}
    >
      <span className={cn("size-1.5 shrink-0 rounded-full", t.solid)} />
      <span className="truncate">{timeLabel(shift.start)} {shift.repName}</span>
    </div>
  );
}

export function MonthGrid({
  cursor,
  shifts,
  now,
  onCreateOnDay,
  onMoveShift,
}: {
  cursor: Date;
  shifts: Shift[];
  now: Date | null;
  onCreateOnDay: (day: Date) => void;
  onMoveShift: (id: string, date: string, start?: string) => void;
}) {
  const days = monthMatrix(cursor);
  const month = cursor.getMonth();

  return (
    <div className="overflow-hidden rounded-3xl border border-line bg-surface shadow-card">
      <div className="grid grid-cols-7 border-b border-line bg-surface-muted/50">
        {WEEKDAYS_SHORT.map((w) => (
          <div key={w} className="px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-faint">
            {w}
          </div>
        ))}
      </div>

      <div className="grid grid-cols-7">
        {days.map((day, i) => {
          const inMonth = day.getMonth() === month;
          const today = now ? isSameDay(day, now) : false;
          const dayShifts = shifts.filter((s) => s.date === ymd(day));
          return (
            <motion.div
              key={day.toISOString()}
              onClick={() => onCreateOnDay(day)}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                const id = e.dataTransfer.getData("text/shift");
                if (id) onMoveShift(id, ymd(day));
              }}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: Math.min(i * 0.004, 0.2) }}
              className={cn(
                "min-h-[112px] cursor-pointer border-b border-l border-line-soft p-1.5 transition-colors hover:bg-surface-muted/50",
                i % 7 === 0 && "border-l-0",
                !inMonth && "bg-surface-muted/30",
              )}
            >
              <div className="mb-1 flex justify-end">
                <span
                  className={cn(
                    "grid size-6 place-items-center rounded-full text-[12px] font-semibold",
                    today ? "bg-primary text-white" : inMonth ? "text-ink" : "text-faint",
                  )}
                >
                  {day.getDate()}
                </span>
              </div>
              <div className="flex flex-col gap-1">
                {dayShifts.slice(0, 3).map((s) => (
                  <Chip key={s.id} shift={s} />
                ))}
                {dayShifts.length > 3 && (
                  <span className="px-1 text-[10px] font-medium text-muted">
                    +{dayShifts.length - 3} more
                  </span>
                )}
              </div>
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}
