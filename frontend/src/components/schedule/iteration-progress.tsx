"use client";

import { useCallback, useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { subscribeTable } from "@/lib/realtime";
import type { ScheduleRun, ScheduleRunIteration } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

type Props = {
  scheduleRunId: string;
};

export function IterationProgress({ scheduleRunId }: Props) {
  const supabase = createClient();
  const [run, setRun] = useState<ScheduleRun | null>(null);
  const [iterations, setIterations] = useState<ScheduleRunIteration[]>([]);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    const [runRes, iterRes] = await Promise.all([
      supabase.from("schedule_runs").select("*").eq("id", scheduleRunId).single(),
      supabase
        .from("schedule_run_iterations")
        .select("*")
        .eq("schedule_run_id", scheduleRunId)
        .order("iteration_number"),
    ]);
    if (runRes.data) setRun(runRes.data as ScheduleRun);
    setIterations((iterRes.data ?? []) as ScheduleRunIteration[]);
    setLoading(false);
  }, [scheduleRunId, supabase]);

  useEffect(() => {
    void reload();
    const unsub1 = subscribeTable(
      supabase,
      `iter:${scheduleRunId}`,
      "schedule_run_iterations",
      `schedule_run_id=eq.${scheduleRunId}`,
      () => void reload(),
    );
    const unsub2 = subscribeTable(
      supabase,
      `run-status:${scheduleRunId}`,
      "schedule_runs",
      `id=eq.${scheduleRunId}`,
      () => void reload(),
    );
    return () => {
      unsub1();
      unsub2();
    };
  }, [scheduleRunId, reload, supabase]);

  if (loading) {
    return <Skeleton className="h-24 w-full" />;
  }

  return (
    <Card className="border-dashed">
      <CardHeader className="py-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm">Orchestrator progress</CardTitle>
          {run ? (
            <Badge variant={run.status === "running" ? "secondary" : "outline"}>{run.status}</Badge>
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        {iterations.length === 0 ? (
          <p className="text-muted-foreground text-sm">Waiting for critic iterations…</p>
        ) : (
          <ul className="space-y-2">
            {iterations.map((it) => (
              <li
                key={it.id}
                className="flex items-start gap-2 rounded border bg-background p-2 text-sm"
              >
                <Badge variant={it.approved ? "default" : "destructive"} className="shrink-0">
                  #{it.iteration_number}
                </Badge>
                <div>
                  <span className="font-medium">{it.approved ? "Approved" : "Rejected"}</span>
                  {it.issues?.length ? (
                    <p className="text-muted-foreground mt-0.5 text-xs">{it.issues[0]}</p>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
