"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { Plus, Layers, Route as RouteIcon, MapPin, Sparkles, Users, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/segmented";
import { Progress } from "@/components/ui/progress";
import { Avatar } from "@/components/ui/avatar";
import { RouteStatusBadge } from "@/components/ui/status";
import { EmptyState } from "@/components/ui/empty-state";
import { FieldMap } from "@/components/maps/field-map";
import { CreateRouteDrawer } from "./create-route-drawer";
import { GenerateRoutesDrawer } from "./generate-routes-drawer";
import { RoutePreviewPanel } from "./route-preview-panel";
import { cn, initials } from "@/lib/utils";
import { fadeInUp, staggerContainer } from "@/lib/motion";
import type { Rep, Route, RoutePartner, Shift } from "@/lib/types";

const legend = [
  { label: "Answered", color: "#34d399" },
  { label: "Lead", color: "#059e6e" },
  { label: "Callback", color: "#f5a623" },
  { label: "Not interested", color: "#fb7185" },
  { label: "Unhit", color: "#cbd3cf" },
];

const TORONTO = { lat: 43.6629, lng: -79.3957 };

function PairStack({ partners }: { partners: RoutePartner[] }) {
  if (!partners.length) return null;
  return (
    <div className="flex items-center -space-x-2">
      {partners.slice(0, 3).map((p) => (
        <span key={p.id} className="ring-2 ring-surface rounded-full">
          <Avatar name={p.name} tint={p.tint} size="sm" />
        </span>
      ))}
    </div>
  );
}

export function RoutesView({
  routes,
  reps,
  shifts,
  teamId,
}: {
  routes: Route[];
  reps: Rep[];
  shifts: Shift[];
  teamId: string | null;
}) {
  const router = useRouter();
  const [selectedId, setSelectedId] = useState(routes[0]?.id);
  const [mode, setMode] = useState<"route" | "coverage">("route");
  const [createOpen, setCreateOpen] = useState(false);
  const [genOpen, setGenOpen] = useState(false);
  const [previewGenId, setPreviewGenId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);

  const deleteRoute = async (id: string) => {
    setDeleting(id);
    try {
      await fetch(`/api/routes/${id}`, { method: "DELETE" });
      router.refresh();
    } finally {
      setDeleting(null);
    }
  };

  if (previewGenId) {
    return <RoutePreviewPanel genId={previewGenId} onClose={() => setPreviewGenId(null)} />;
  }

  const selected = routes.find((r) => r.id === selectedId) ?? routes[0];
  const coverageTrail = useMemo(
    () =>
      routes.flatMap((r) =>
        r.path.filter((_, i) => i % 3 === 0).map((position, i) => ({
          id: `${r.id}-${i}`,
          at: r.createdAt,
          position,
          outcome: "answered" as const,
        })),
      ),
    [routes],
  );

  if (!selected) {
    return (
      <div className="mx-auto max-w-[1100px]">
        <div className="rounded-3xl border border-line bg-surface shadow-card">
          <EmptyState
            icon={<RouteIcon className="size-6" />}
            title="No routes yet"
            description="Generate street-following routes with AI — it pulls who's on shift, pairs them up two-per-route, sizes each to the shift, and avoids streets you've already covered."
            action={
              <div className="flex gap-2">
                <Button size="sm" onClick={() => setGenOpen(true)}>
                  <Sparkles className="size-4" /> Generate with AI
                </Button>
                <Button size="sm" variant="secondary" onClick={() => setCreateOpen(true)}>
                  <Plus className="size-4" /> Add manually
                </Button>
              </div>
            }
          />
        </div>
        <GenerateRoutesDrawer open={genOpen} onOpenChange={setGenOpen} reps={reps} shifts={shifts} teamId={teamId} onPreview={setPreviewGenId} />
        <CreateRouteDrawer open={createOpen} onOpenChange={setCreateOpen} reps={reps} teamId={teamId} />
      </div>
    );
  }

  const partners = selected.assignedMarketers ?? [];

  return (
    <div className="mx-auto flex max-w-[1500px] flex-col gap-4">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[360px_1fr]">
        <div className="flex flex-col gap-3">
          <Button onClick={() => setGenOpen(true)} className="w-full">
            <Sparkles className="size-4" /> Generate with AI
          </Button>
          <button
            onClick={() => setCreateOpen(true)}
            className="-mt-1 self-center text-[12px] font-medium text-muted transition-colors hover:text-ink"
          >
            or add a route manually
          </button>

          <motion.div
            variants={staggerContainer(0.05)}
            initial="hidden"
            animate="show"
            className="flex flex-col gap-2.5"
          >
            {routes.map((route) => {
              const active = route.id === selected.id;
              const rp = route.assignedMarketers ?? [];
              return (
                <motion.div
                  key={route.id}
                  variants={fadeInUp}
                  role="button"
                  tabIndex={0}
                  onClick={() => {
                    setSelectedId(route.id);
                    setMode("route");
                  }}
                  className={cn(
                    "group relative cursor-pointer rounded-3xl border p-4 text-left shadow-soft transition-all",
                    active
                      ? "border-primary-200 bg-primary-50/50 ring-1 ring-primary-100"
                      : "border-line bg-surface hover:bg-surface-muted",
                  )}
                >
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      deleteRoute(route.id);
                    }}
                    disabled={deleting === route.id}
                    title="Delete route"
                    className="absolute bottom-3 right-3 z-10 grid size-7 place-items-center rounded-lg text-faint opacity-0 transition-all hover:bg-rose-50 hover:text-[#be123c] group-hover:opacity-100 disabled:opacity-40"
                  >
                    <Trash2 className="size-3.5" />
                  </button>
                  <div className="flex items-start gap-3">
                    <span
                      className={cn(
                        "grid size-10 shrink-0 place-items-center rounded-xl text-[11px] font-bold",
                        active ? "bg-primary-100 text-primary-700" : "bg-canvas-deep text-ink-soft",
                      )}
                    >
                      {initials(route.territory)}
                    </span>
                    <div className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-semibold text-ink">{route.name}</span>
                      <div className="mt-0.5 flex items-center gap-2">
                        <RouteStatusBadge status={route.status} size="sm" />
                      </div>
                    </div>
                    <PairStack partners={rp} />
                  </div>

                  <div className="mt-3">
                    <div className="mb-1 flex items-center justify-between text-[11px]">
                      <span className="text-muted">Coverage</span>
                      <span className="nums font-semibold text-ink-soft">
                        {route.doorsHit}/{route.doorsPlanned} doors
                      </span>
                    </div>
                    <Progress value={route.coverage} height="h-1.5" />
                  </div>

                  <div className="mt-3 flex items-center gap-4 text-[12px] text-muted">
                    {rp.length > 0 && (
                      <span className="inline-flex items-center gap-1">
                        <Users className="size-3.5" />
                        {rp.map((p) => p.name.split(" ")[0]).join(" & ")}
                      </span>
                    )}
                  </div>
                </motion.div>
              );
            })}
          </motion.div>
        </div>

        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="text-base font-bold tracking-tight text-ink">{selected.name}</h3>
              <p className="flex items-center gap-2 text-[12px] text-muted">
                <span className="inline-flex items-center gap-1">
                  <MapPin className="size-3.5" /> {selected.territory}
                </span>
                {partners.length > 0 && (
                  <span className="inline-flex items-center gap-1">
                    <Users className="size-3.5" /> {partners.map((p) => p.name.split(" ")[0]).join(" & ")}
                  </span>
                )}
              </p>
            </div>
            <Segmented
              size="sm"
              value={mode}
              onChange={setMode}
              options={[
                { value: "route", label: <span className="inline-flex items-center gap-1.5"><RouteIcon className="size-3.5" /> Route</span> },
                { value: "coverage", label: <span className="inline-flex items-center gap-1.5"><Layers className="size-3.5" /> Coverage</span> },
              ]}
            />
          </div>

          <div className="relative h-[600px] overflow-hidden rounded-3xl border border-line shadow-card">
            <FieldMap
              key={mode + selected.id}
              center={selected.center ?? TORONTO}
              path={mode === "route" ? selected.path : undefined}
              trail={mode === "coverage" ? coverageTrail : []}
              progress={1}
              mode={mode}
              className="h-full"
            />

            <div className="absolute bottom-3 left-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-2xl bg-surface/85 px-3 py-2 shadow-soft backdrop-blur">
              {legend.map((l) => (
                <span key={l.label} className="inline-flex items-center gap-1.5 text-[11px] font-medium text-ink-soft">
                  <span className="size-2 rounded-full" style={{ backgroundColor: l.color }} />
                  {l.label}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>

      <GenerateRoutesDrawer open={genOpen} onOpenChange={setGenOpen} reps={reps} shifts={shifts} teamId={teamId} onPreview={setPreviewGenId} />
      <CreateRouteDrawer open={createOpen} onOpenChange={setCreateOpen} reps={reps} teamId={teamId} />
    </div>
  );
}
