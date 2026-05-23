"use client";

import type { CrewRoute, OptimizerLabCrew, OptimizerLabJob } from "@/lib/optimizer-lab-api";
import { formatMinute } from "@/lib/format";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const DAY_START = 6 * 60;
const DAY_END = 18 * 60;
const SLOT = 30;

type Props = {
  targetDate: string;
  routes: CrewRoute[];
  crews: OptimizerLabCrew[];
  jobs: Record<string, OptimizerLabJob>;
  unassignedIds: string[];
  messages: string[];
  status: string;
  durationSeconds: number;
};

function timeSlots(): number[] {
  const out: number[] = [];
  for (let m = DAY_START; m < DAY_END; m += SLOT) {
    out.push(m);
  }
  return out;
}

function stopAtSlot(stops: CrewRoute["stops"], slotStart: number): CrewRoute["stops"][0] | null {
  const slotEnd = slotStart + SLOT;
  return (
    stops.find((s) => s.arrival_minute < slotEnd && s.depart_minute > slotStart) ?? null
  );
}

export function ScheduleGrid({
  targetDate,
  routes,
  crews,
  jobs,
  unassignedIds,
  messages,
  status,
  durationSeconds,
}: Props) {
  const slots = timeSlots();
  const crewNames = Object.fromEntries(crews.map((c) => [c.crew_id, c.name]));
  const activeRoutes = routes.filter((r) => r.stops.length > 0);
  const ok = status === "feasible" || status === "optimal";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <Badge variant={ok ? "default" : "destructive"}>{status}</Badge>
        <Badge variant="outline">{durationSeconds}s solve time</Badge>
        <Badge variant="secondary">{activeRoutes.length} crews with routes</Badge>
        <Badge variant="outline">{unassignedIds.length} unassigned</Badge>
      </div>

      {messages.length > 0 ? (
        <Card className="border-amber-500/50 bg-amber-500/5">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Optimizer diagnostics</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="list-disc space-y-1 pl-4 text-sm">
              {messages.map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Schedule grid — {targetDate}</CardTitle>
          <p className="text-muted-foreground text-xs">
            Rows = crews. Columns = 30-minute slots (6:00–18:00). Colored cells = job on route.
          </p>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full min-w-[900px] border-collapse text-xs">
            <thead>
              <tr className="bg-muted/50">
                <th className="sticky left-0 z-10 border bg-muted/80 p-2 text-left font-medium">
                  Crew
                </th>
                {slots.map((m) => (
                  <th key={m} className="border p-1 text-center font-normal whitespace-nowrap">
                    {formatMinute(m)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {activeRoutes.length === 0 ? (
                <tr>
                  <td
                    colSpan={slots.length + 1}
                    className="text-muted-foreground border p-6 text-center"
                  >
                    No routes — optimizer assigned zero jobs. Check diagnostics and edit jobs
                    (skills/equipment/dates) then run again.
                  </td>
                </tr>
              ) : (
                activeRoutes.map((route) => (
                  <tr key={route.crew_id}>
                    <td className="sticky left-0 z-10 border bg-background p-2 font-medium whitespace-nowrap">
                      {crewNames[route.crew_id] ?? route.crew_id}
                      <div className="text-muted-foreground font-normal">
                        {route.total_travel_minutes}m drive · {route.total_service_minutes}m work
                      </div>
                    </td>
                    {slots.map((slotStart) => {
                      const hit = stopAtSlot(route.stops, slotStart);
                      if (!hit) {
                        return <td key={slotStart} className="border p-0.5" />;
                      }
                      const job = jobs[hit.job_id];
                      const isStart =
                        hit.arrival_minute >= slotStart && hit.arrival_minute < slotStart + SLOT;
                      return (
                        <td
                          key={slotStart}
                          className={
                            isStart
                              ? "border bg-primary text-primary-foreground p-1 align-top min-w-[72px]"
                              : "border bg-primary/25 p-0.5"
                          }
                          title={`${hit.job_id} ${formatMinute(hit.arrival_minute)}–${formatMinute(hit.depart_minute)}`}
                        >
                          {isStart ? (
                            <>
                              <div className="font-semibold">{hit.job_id}</div>
                              <div className="opacity-90 text-[10px]">
                                {job?.service_type?.replace(/_/g, " ")}
                              </div>
                            </>
                          ) : null}
                        </td>
                      );
                    })}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>

      {activeRoutes.length > 0 ? (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Stop order (detail)</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {activeRoutes.map((route) => (
              <div key={route.crew_id}>
                <div className="font-medium text-sm">
                  {crewNames[route.crew_id] ?? route.crew_id}
                </div>
                <ol className="mt-1 list-decimal pl-5 text-sm">
                  {route.stops.map((s, i) => {
                    const prev = i > 0 ? route.stops[i - 1] : null;
                    const drive = prev ? s.arrival_minute - prev.depart_minute : 0;
                    return (
                      <li key={`${s.job_id}-${i}`}>
                        {drive > 0 ? (
                          <span className="text-muted-foreground">{drive}m drive → </span>
                        ) : null}
                        <span className="font-mono">{s.job_id}</span>{" "}
                        {formatMinute(s.arrival_minute)}–{formatMinute(s.depart_minute)}
                        {jobs[s.job_id] ? (
                          <span className="text-muted-foreground"> — {jobs[s.job_id].address}</span>
                        ) : null}
                      </li>
                    );
                  })}
                </ol>
              </div>
            ))}
          </CardContent>
        </Card>
      ) : null}

      {unassignedIds.length > 0 ? (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Unassigned jobs</CardTitle>
          </CardHeader>
          <CardContent>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-muted-foreground text-left text-xs">
                  <th className="p-2">ID</th>
                  <th className="p-2">Service</th>
                  <th className="p-2">Skills</th>
                  <th className="p-2">Equipment</th>
                  <th className="p-2">Address</th>
                </tr>
              </thead>
              <tbody>
                {unassignedIds.map((id) => {
                  const j = jobs[id];
                  return (
                    <tr key={id} className="border-t">
                      <td className="p-2 font-mono text-xs">{id}</td>
                      <td className="p-2">{j?.service_type ?? "—"}</td>
                      <td className="p-2 text-xs">{(j?.required_skills ?? []).join(", ")}</td>
                      <td className="p-2 text-xs">{(j?.required_equipment ?? []).join(", ")}</td>
                      <td className="p-2 text-xs">{j?.address ?? "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
