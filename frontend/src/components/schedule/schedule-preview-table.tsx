"use client";

import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import type { CrewRow, JobRow, SchedulePreview } from "@/lib/types";
import { formatDateLabel, formatMinute } from "@/lib/format";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { approveSchedule, rejectSchedule } from "@/lib/api";
import { AlertTriangle, Check, X } from "lucide-react";

type Props = {
  preview: SchedulePreview;
  onDecision?: () => void;
};

export function SchedulePreviewTable({ preview, onDecision }: Props) {
  const supabase = createClient();
  const [jobs, setJobs] = useState<Record<string, JobRow>>({});
  const [crews, setCrews] = useState<Record<string, CrewRow>>({});
  const [runStatus, setRunStatus] = useState(preview.status);
  const [acting, setActing] = useState(false);

  const jobIdsKey = [
    ...preview.routes.flatMap((r) => r.stops.map((s) => s.job_id)),
    ...preview.unassigned_job_ids,
  ].join(",");
  const crewIdsKey = preview.routes.map((r) => r.crew_id).join(",");

  useEffect(() => {
    async function load() {
      const jobIds = jobIdsKey ? jobIdsKey.split(",") : [];
      const crewIds = crewIdsKey ? crewIdsKey.split(",") : [];
      if (jobIds.length) {
        const { data } = await supabase.from("jobs").select("id, address, client_id, estimated_minutes").in("id", jobIds);
        const map: Record<string, JobRow> = {};
        (data ?? []).forEach((j) => {
          map[j.id] = j as JobRow;
        });
        setJobs(map);
      }
      if (crewIds.length) {
        const { data } = await supabase.from("crews").select("id, name").in("id", crewIds);
        const map: Record<string, CrewRow> = {};
        (data ?? []).forEach((c) => {
          map[c.id] = c as CrewRow;
        });
        setCrews(map);
      }
    }
    void load();
  }, [preview.attempt_id, jobIdsKey, crewIdsKey, supabase]);

  useEffect(() => {
    async function loadRun() {
      const { data } = await supabase
        .from("schedule_runs")
        .select("status, approved")
        .eq("id", preview.schedule_run_id)
        .single();
      if (data) setRunStatus(data.status as string);
    }
    void loadRun();

    return subscribeRun(supabase, preview.schedule_run_id, () => {
      void loadRun();
    });
  }, [preview.schedule_run_id]);

  const dayLabel = formatDateLabel(preview.week_start);
  const canDecide =
    runStatus !== "approved" && runStatus !== "rejected" && !preview.approved;

  async function handleApprove() {
    setActing(true);
    try {
      await approveSchedule(preview.schedule_run_id);
      onDecision?.();
    } finally {
      setActing(false);
    }
  }

  async function handleReject() {
    setActing(true);
    try {
      await rejectSchedule(preview.schedule_run_id);
      onDecision?.();
    } finally {
      setActing(false);
    }
  }

  return (
    <Card className="border-primary/20 bg-muted/30">
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-base">Schedule preview — {dayLabel}</CardTitle>
          <div className="flex gap-2">
            <Badge variant={preview.approved ? "default" : "secondary"}>{runStatus}</Badge>
            <Badge variant="outline">{preview.iteration_count} critic pass(es)</Badge>
          </div>
        </div>
        {preview.summary ? (
          <p className="text-muted-foreground text-sm">{preview.summary}</p>
        ) : null}
      </CardHeader>
      <CardContent className="space-y-4">
        {preview.issues.length > 0 ? (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertTitle>Critic warnings</AlertTitle>
            <AlertDescription>
              <ul className="mt-1 list-disc pl-4 text-sm">
                {preview.issues.slice(0, 6).map((issue) => (
                  <li key={issue}>{issue}</li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        ) : null}

        <div className="overflow-x-auto rounded-md border">
          <table className="w-full min-w-[640px] border-collapse text-sm">
            <thead>
              <tr className="bg-muted/60 border-b">
                <th className="p-2 text-left font-medium">Crew</th>
                <th className="p-2 text-left font-medium">{dayLabel}</th>
              </tr>
            </thead>
            <tbody>
              {preview.routes.length === 0 ? (
                <tr>
                  <td colSpan={2} className="text-muted-foreground p-4 text-center">
                    No routes in this attempt.
                  </td>
                </tr>
              ) : (
                preview.routes.filter((route) => route.stops.length > 0).map((route) => (
                  <tr key={route.crew_id} className="border-b align-top">
                    <td className="p-2 font-medium whitespace-nowrap">
                      {crews[route.crew_id]?.name ?? route.crew_id}
                      <div className="text-muted-foreground text-xs font-normal">
                        {route.total_travel_minutes}m drive · {route.total_service_minutes}m work
                      </div>
                    </td>
                    <td className="p-2">
                      <ol className="space-y-2">
                        {route.stops.map((stop, idx) => {
                          const job = jobs[stop.job_id];
                          const prev = idx > 0 ? route.stops[idx - 1] : null;
                          const driveMin = prev
                            ? stop.arrival_minute - prev.depart_minute
                            : null;
                          return (
                            <li key={`${stop.job_id}-${idx}`} className="rounded border bg-background p-2">
                              {driveMin !== null && driveMin > 0 ? (
                                <div className="text-muted-foreground mb-1 text-xs">
                                  ↳ {driveMin} min drive
                                </div>
                              ) : null}
                              <div className="font-medium">{stop.job_id}</div>
                              {job ? (
                                <div className="text-muted-foreground text-xs">{job.address}</div>
                              ) : null}
                              <div className="mt-1 text-xs">
                                Arrive {formatMinute(stop.arrival_minute)} · Work until{" "}
                                {formatMinute(stop.depart_minute)}
                              </div>
                            </li>
                          );
                        })}
                      </ol>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {preview.unassigned_job_ids.length > 0 ? (
          <Alert>
            <AlertTitle>Unassigned jobs ({preview.unassigned_job_ids.length})</AlertTitle>
            <AlertDescription className="text-xs">
              {preview.unassigned_job_ids.slice(0, 8).join(", ")}
              {preview.unassigned_job_ids.length > 8 ? "…" : ""}
            </AlertDescription>
          </Alert>
        ) : null}

        {canDecide ? (
          <div className="flex gap-2">
            <Button size="sm" onClick={() => void handleApprove()} disabled={acting}>
              <Check className="mr-1 h-4 w-4" />
              Approve
            </Button>
            <Button size="sm" variant="outline" onClick={() => void handleReject()} disabled={acting}>
              <X className="mr-1 h-4 w-4" />
              Reject
            </Button>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function subscribeRun(
  supabase: ReturnType<typeof createClient>,
  runId: string,
  onChange: () => void,
) {
  const channel = supabase
    .channel(`run:${runId}`)
    .on(
      "postgres_changes",
      {
        event: "*",
        schema: "public",
        table: "schedule_runs",
        filter: `id=eq.${runId}`,
      },
      () => onChange(),
    )
    .subscribe();
  return () => {
    void supabase.removeChannel(channel);
  };
}
