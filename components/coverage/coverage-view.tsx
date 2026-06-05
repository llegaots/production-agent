"use client";

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import { Map as MapIcon, Users, DoorOpen, CalendarDays } from "lucide-react";
import { EmptyState } from "@/components/ui/empty-state";
import { CoverageMap, type CoverageRoute } from "@/components/maps/coverage-map";
import { cn } from "@/lib/utils";
import { fadeInUp, staggerContainer } from "@/lib/motion";
import type { LatLng, Route } from "@/lib/types";

const PALETTE = ["#059e6e", "#2563eb", "#d97706", "#7c3aed", "#dc2626", "#0891b2", "#db2777", "#65a30d"];
const TORONTO = { lat: 43.6629, lng: -79.3957 };

const routeDay = (r: Route) => (r.scheduledFor ?? r.createdAt ?? "").slice(0, 10);

function fmtDay(ymd: string) {
  const d = new Date(ymd + "T00:00:00");
  return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

export function CoverageView({ routes }: { routes: Route[] }) {
  const [day, setDay] = useState<string>("all");
  const [hover, setHover] = useState<string | null>(null);

  const days = useMemo(() => {
    const set = new Set<string>();
    routes.forEach((r) => {
      const d = routeDay(r);
      if (d) set.add(d);
    });
    return [...set].sort((a, b) => b.localeCompare(a));
  }, [routes]);

  const filtered = useMemo(
    () => (day === "all" ? routes : routes.filter((r) => routeDay(r) === day)),
    [routes, day],
  );

  const coverageRoutes: CoverageRoute[] = useMemo(
    () =>
      filtered
        .filter((r) => r.path.length > 1)
        .map((r, i) => ({ id: r.id, name: r.name, path: r.path, color: PALETTE[i % PALETTE.length] })),
    [filtered],
  );

  const center: LatLng = filtered[0]?.center ?? routes[0]?.center ?? TORONTO;
  const totals = useMemo(() => {
    const planned = filtered.reduce((s, r) => s + (r.doorsPlanned || 0), 0);
    const hit = filtered.reduce((s, r) => s + (r.doorsHit || 0), 0);
    return { planned, hit, pct: planned ? Math.round((hit / planned) * 100) : 0 };
  }, [filtered]);

  if (!routes.length) {
    return (
      <div className="mx-auto max-w-[1100px]">
        <div className="rounded-3xl border border-line bg-surface shadow-card">
          <EmptyState
            icon={<MapIcon className="size-6" />}
            title="No coverage yet"
            description="Once you generate and confirm routes, every one shows up here so you can see exactly where your team has been across all shifts."
          />
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-[1500px] flex-col gap-4">
      {/* date filter */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="mr-1 inline-flex items-center gap-1.5 text-[12px] font-medium text-muted">
          <CalendarDays className="size-3.5" /> Filter
        </span>
        <DayChip active={day === "all"} onClick={() => setDay("all")} label={`All shifts (${routes.length})`} />
        {days.map((d) => {
          const count = routes.filter((r) => routeDay(r) === d).length;
          return <DayChip key={d} active={day === d} onClick={() => setDay(d)} label={`${fmtDay(d)} (${count})`} />;
        })}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[340px_1fr]">
        {/* sidebar */}
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-3 gap-2">
            <Stat label="Routes" value={filtered.length} />
            <Stat label="Doors" value={totals.planned} />
            <Stat label="Hit" value={`${totals.pct}%`} />
          </div>

          <motion.div variants={staggerContainer(0.04)} initial="hidden" animate="show" className="flex flex-col gap-2">
            {filtered.map((r, i) => (
              <motion.div
                key={r.id}
                variants={fadeInUp}
                onMouseEnter={() => setHover(r.id)}
                onMouseLeave={() => setHover(null)}
                className={cn(
                  "flex items-center gap-3 rounded-2xl border p-3 transition-colors",
                  hover === r.id ? "border-primary-200 bg-primary-50/40" : "border-line bg-surface",
                )}
              >
                <span className="mt-0.5 size-3 shrink-0 rounded-full" style={{ backgroundColor: PALETTE[i % PALETTE.length] }} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[13px] font-semibold text-ink">{r.name}</div>
                  <div className="mt-0.5 flex items-center gap-3 text-[11px] text-muted">
                    <span className="inline-flex items-center gap-1">
                      <DoorOpen className="size-3" /> {r.doorsPlanned} doors
                    </span>
                    {(r.assignedMarketers?.length ?? 0) > 0 && (
                      <span className="inline-flex items-center gap-1">
                        <Users className="size-3" />
                        {(r.assignedMarketers ?? []).map((p) => p.name.split(" ")[0]).join(" & ")}
                      </span>
                    )}
                  </div>
                </div>
                <span className="shrink-0 text-[10px] font-medium text-faint">{fmtDay(routeDay(r))}</span>
              </motion.div>
            ))}
          </motion.div>
        </div>

        {/* map */}
        <div className="relative h-[640px] overflow-hidden rounded-3xl border border-line shadow-card">
          <CoverageMap
            key={day}
            routes={coverageRoutes}
            center={center}
            highlightId={hover}
            className="h-full"
          />
        </div>
      </div>
    </div>
  );
}

function DayChip({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "rounded-full border px-3 py-1.5 text-[12px] font-medium transition-colors",
        active
          ? "border-primary-200 bg-primary-50 text-primary-700"
          : "border-line bg-surface text-ink-soft hover:bg-surface-muted",
      )}
    >
      {label}
    </button>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-2xl border border-line bg-surface px-3 py-2.5 text-center shadow-soft">
      <div className="nums text-lg font-bold text-ink">{value}</div>
      <div className="text-[11px] font-medium text-muted">{label}</div>
    </div>
  );
}
