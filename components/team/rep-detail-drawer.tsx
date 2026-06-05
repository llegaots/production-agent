"use client";

import { Mail, Phone, MapPin, Route as RouteIcon, CalendarDays, DoorOpen, Sparkles, Timer } from "lucide-react";
import { Drawer } from "@/components/ui/drawer";
import { Avatar } from "@/components/ui/avatar";
import { Gauge } from "@/components/ui/gauge";
import { RepStatusBadge, RouteStatusBadge } from "@/components/ui/status";
import { cn } from "@/lib/utils";
import type { Rep, Route, Shift } from "@/lib/types";

function Stat({ icon, label, value, chip }: { icon: React.ReactNode; label: string; value: string | number; chip: string }) {
  return (
    <div className="flex items-center gap-3 rounded-2xl border border-line bg-surface px-3.5 py-3 shadow-soft">
      <span className={cn("grid size-9 place-items-center rounded-xl", chip)}>{icon}</span>
      <div>
        <div className="nums text-lg font-bold text-ink">{value}</div>
        <div className="text-[11px] font-medium uppercase tracking-wide text-faint">{label}</div>
      </div>
    </div>
  );
}

function MetaRow({ icon, value }: { icon: React.ReactNode; value: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2.5 border-b border-line-soft py-2.5 text-[13px] text-ink-soft last:border-0">
      <span className="text-muted">{icon}</span>
      {value}
    </div>
  );
}

export function RepDetailDrawer({
  rep,
  routes,
  shifts,
  open,
  onOpenChange,
}: {
  rep: Rep | null;
  routes: Route[];
  shifts: Shift[];
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const repRoutes = rep ? routes.filter((r) => (r.assignedMarketers ?? []).some((m) => m.id === rep.id)) : [];
  const repShifts = rep
    ? shifts.filter((s) => s.repId === rep.id).sort((a, b) => a.date.localeCompare(b.date))
    : [];

  return (
    <Drawer open={open} onOpenChange={onOpenChange} title={rep?.name} description={rep?.territory} widthClass="max-w-lg">
      {rep && (
        <div className="flex flex-col gap-5 p-6">
          <div className="flex items-center gap-4">
            <Avatar name={rep.name} tint={rep.avatarTint} size="xl" status={rep.status} />
            <div>
              <h3 className="font-display text-xl font-extrabold tracking-tight text-ink">{rep.name}</h3>
              <div className="mt-1 flex items-center gap-2">
                <RepStatusBadge status={rep.status} size="sm" />
                <span className="inline-flex items-center gap-1 text-[12px] text-muted">
                  <MapPin className="size-3.5" /> {rep.territory || "-"}
                </span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-5 rounded-3xl border border-line bg-surface-muted/40 p-4">
            <Gauge value={rep.grade} size={110} stroke={10} />
            <div className="flex-1 text-[13px]">
              <div className="flex items-center justify-between py-1">
                <span className="text-muted">Answer rate</span>
                <span className="nums font-semibold text-ink">{rep.answerRate}%</span>
              </div>
              <div className="flex items-center justify-between py-1">
                <span className="text-muted">Conversion</span>
                <span className="nums font-semibold text-ink">{rep.conversionRate}%</span>
              </div>
              <div className="flex items-center justify-between py-1">
                <span className="text-muted">Joined</span>
                <span className="font-semibold text-ink">{new Date(rep.joinedAt).toLocaleDateString()}</span>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-2.5">
            <Stat icon={<DoorOpen className="size-4.5" />} label="Doors" value={rep.doorsToday} chip="bg-primary-50 text-primary-700" />
            <Stat icon={<Sparkles className="size-4.5" />} label="Leads" value={rep.leadsToday} chip="bg-violet-50 text-[#6d28d9]" />
            <Stat icon={<Timer className="size-4.5" />} label="Pace" value={`${rep.pace}/hr`} chip="bg-amber-50 text-[#b45309]" />
          </div>

          {(rep.email || rep.phone) && (
            <div className="rounded-2xl border border-line p-4">
              {rep.email && <MetaRow icon={<Mail className="size-3.5" />} value={rep.email} />}
              {rep.phone && <MetaRow icon={<Phone className="size-3.5" />} value={rep.phone} />}
            </div>
          )}

          <div>
            <h4 className="mb-2 flex items-center gap-1.5 text-[13px] font-semibold text-ink-soft">
              <RouteIcon className="size-4 text-primary-600" /> Assigned routes ({repRoutes.length})
            </h4>
            <div className="flex flex-col gap-2">
              {repRoutes.length === 0 && (
                <p className="rounded-2xl border border-dashed border-line bg-surface-muted/50 px-3 py-3 text-[12px] text-muted">
                  No routes assigned yet.
                </p>
              )}
              {repRoutes.map((r) => (
                <div key={r.id} className="flex items-center justify-between rounded-2xl border border-line p-3">
                  <div className="min-w-0">
                    <div className="truncate text-[13px] font-semibold text-ink">{r.name}</div>
                    <div className="text-[11px] text-muted">{r.doorsPlanned} doors planned</div>
                  </div>
                  <RouteStatusBadge status={r.status} size="sm" />
                </div>
              ))}
            </div>
          </div>

          <div>
            <h4 className="mb-2 flex items-center gap-1.5 text-[13px] font-semibold text-ink-soft">
              <CalendarDays className="size-4 text-primary-600" /> Shifts ({repShifts.length})
            </h4>
            <div className="flex flex-col gap-1.5">
              {repShifts.length === 0 && (
                <p className="rounded-2xl border border-dashed border-line bg-surface-muted/50 px-3 py-3 text-[12px] text-muted">
                  No shifts scheduled.
                </p>
              )}
              {repShifts.slice(0, 8).map((s) => (
                <div key={s.id} className="flex items-center justify-between rounded-xl bg-surface-muted px-3 py-2 text-[12px]">
                  <span className="font-medium text-ink">{new Date(s.date + "T00:00:00").toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}</span>
                  <span className="nums text-muted">{s.start}-{s.end}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </Drawer>
  );
}
