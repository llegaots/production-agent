"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  deleteLabJob,
  fetchLabCrews,
  fetchLabJobs,
  runLabOptimizer,
  updateLabJob,
  type OptimizerLabJob,
  type OptimizerRunResult,
} from "@/lib/optimizer-lab-api";
import { ScheduleGrid } from "@/components/optimizer-lab/schedule-grid";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Loader2, Play, RefreshCw, Trash2 } from "lucide-react";

type EditableJob = OptimizerLabJob & { selected: boolean };

const SERVICE_TYPES = [
  "window_cleaning",
  "gutter_cleaning",
  "pressure_washing",
  "solar_panel_cleaning",
  "high_rise",
];

export function OptimizerLab() {
  const [idPrefix, setIdPrefix] = useState("qa_job_");
  const [idFrom, setIdFrom] = useState("qa_job_006");
  const [idTo, setIdTo] = useState("qa_job_012");
  const [targetDate, setTargetDate] = useState("2026-07-08");
  const [jobs, setJobs] = useState<EditableJob[]>([]);
  const [drafts, setDrafts] = useState<Record<string, Partial<OptimizerLabJob>>>({});
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<OptimizerRunResult | null>(null);
  const [crews, setCrews] = useState<Awaited<ReturnType<typeof fetchLabCrews>>>([]);

  const loadJobs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const rows = await fetchLabJobs({
        id_prefix: idPrefix || undefined,
        id_from: idFrom || undefined,
        id_to: idTo || undefined,
        target_date: targetDate || undefined,
        limit: 200,
      });
      setJobs(
        rows.map((j) => ({
          ...j,
          selected: true,
        })),
      );
      setDrafts({});
      const c = await fetchLabCrews(targetDate);
      setCrews(c);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load jobs");
    } finally {
      setLoading(false);
    }
  }, [idPrefix, idFrom, idTo, targetDate]);

  useEffect(() => {
    void loadJobs();
  }, [loadJobs]);

  const jobsById = useMemo(() => {
    const m: Record<string, OptimizerLabJob> = {};
    for (const j of jobs) {
      m[j.id] = { ...j, ...drafts[j.id] };
    }
    return m;
  }, [jobs, drafts]);

  const selectedIds = jobs.filter((j) => j.selected).map((j) => j.id);

  function patchDraft(id: string, patch: Partial<OptimizerLabJob>) {
    setDrafts((d) => ({ ...d, [id]: { ...d[id], ...patch } }));
  }

  function getRow(id: string): OptimizerLabJob {
    return { ...jobsById[id] };
  }

  async function saveRow(id: string) {
    const patch = drafts[id];
    if (!patch) return;
    setError(null);
    try {
      const updated = await updateLabJob(id, patch);
      setJobs((list) => list.map((j) => (j.id === id ? { ...j, ...updated, selected: j.selected } : j)));
      setDrafts((d) => {
        const next = { ...d };
        delete next[id];
        return next;
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    }
  }

  async function removeRow(id: string) {
    if (!confirm(`Delete job ${id} from Supabase?`)) return;
    setError(null);
    try {
      await deleteLabJob(id);
      setJobs((list) => list.filter((j) => j.id !== id));
      setDrafts((d) => {
        const next = { ...d };
        delete next[id];
        return next;
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    }
  }

  async function handleRun() {
    if (selectedIds.length === 0) {
      setError("Select at least one job");
      return;
    }
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const res = await runLabOptimizer({
        target_date: targetDate,
        job_ids: selectedIds,
      });
      setResult(res);
      const c = await fetchLabCrews(targetDate);
      setCrews(c);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Optimizer run failed");
    } finally {
      setRunning(false);
    }
  }

  function toggleAll(on: boolean) {
    setJobs((list) => list.map((j) => ({ ...j, selected: on })));
  }

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
        <div>
          <h1 className="text-lg font-semibold">OR-Tools Optimizer Lab</h1>
          <p className="text-muted-foreground text-sm">
            Edit Supabase jobs, run the solver only, inspect the grid.{" "}
            <Link href="/chat" className="underline">
              Back to chat
            </Link>
          </p>
        </div>
        <Button onClick={() => void handleRun()} disabled={running || selectedIds.length === 0}>
          {running ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Play className="mr-2 h-4 w-4" />
          )}
          Run optimizer ({selectedIds.length} jobs)
        </Button>
      </header>

      <div className="grid flex-1 gap-4 p-4 lg:grid-cols-2">
        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Load jobs from Supabase</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="grid grid-cols-2 gap-2 text-sm">
                <label className="space-y-1">
                  <span className="text-muted-foreground text-xs">ID prefix</span>
                  <Input value={idPrefix} onChange={(e) => setIdPrefix(e.target.value)} />
                </label>
                <label className="space-y-1">
                  <span className="text-muted-foreground text-xs">Schedule date</span>
                  <Input
                    type="date"
                    value={targetDate}
                    onChange={(e) => setTargetDate(e.target.value)}
                  />
                </label>
                <label className="space-y-1">
                  <span className="text-muted-foreground text-xs">ID from</span>
                  <Input value={idFrom} onChange={(e) => setIdFrom(e.target.value)} />
                </label>
                <label className="space-y-1">
                  <span className="text-muted-foreground text-xs">ID to</span>
                  <Input value={idTo} onChange={(e) => setIdTo(e.target.value)} />
                </label>
              </div>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={() => void loadJobs()} disabled={loading}>
                  <RefreshCw className={`mr-1 h-3 w-3 ${loading ? "animate-spin" : ""}`} />
                  Reload
                </Button>
                <Button variant="outline" size="sm" onClick={() => toggleAll(true)}>
                  Select all
                </Button>
                <Button variant="outline" size="sm" onClick={() => toggleAll(false)}>
                  Clear
                </Button>
              </div>
              {crews.length > 0 ? (
                <p className="text-muted-foreground text-xs">
                  {crews.filter((c) => c.is_available).length} crews available on {targetDate}
                </p>
              ) : null}
            </CardContent>
          </Card>

          {error ? (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}

          <Card className="flex max-h-[calc(100vh-12rem)] flex-col overflow-hidden">
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Jobs ({jobs.length})</CardTitle>
            </CardHeader>
            <CardContent className="flex-1 overflow-auto p-0">
              {loading ? (
                <p className="text-muted-foreground p-4 text-sm">Loading…</p>
              ) : jobs.length === 0 ? (
                <p className="text-muted-foreground p-4 text-sm">No jobs match filters.</p>
              ) : (
                <table className="w-full text-xs">
                  <thead className="bg-muted/60 sticky top-0">
                    <tr>
                      <th className="p-2">✓</th>
                      <th className="p-2 text-left">ID</th>
                      <th className="p-2 text-left">Service</th>
                      <th className="p-2 text-left">Min</th>
                      <th className="p-2 text-left">Skills</th>
                      <th className="p-2 text-left">Equipment</th>
                      <th className="p-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {jobs.map((j) => {
                      const row = getRow(j.id);
                      const dirty = Boolean(drafts[j.id]);
                      return (
                        <tr key={j.id} className="border-t align-top">
                          <td className="p-2">
                            <input
                              type="checkbox"
                              checked={j.selected}
                              onChange={(e) =>
                                setJobs((list) =>
                                  list.map((x) =>
                                    x.id === j.id ? { ...x, selected: e.target.checked } : x,
                                  ),
                                )
                              }
                            />
                          </td>
                          <td className="p-2 font-mono">{j.id}</td>
                          <td className="p-2">
                            <select
                              className="w-full rounded border bg-background px-1 py-0.5"
                              value={row.service_type}
                              onChange={(e) =>
                                patchDraft(j.id, { service_type: e.target.value })
                              }
                            >
                              {SERVICE_TYPES.map((s) => (
                                <option key={s} value={s}>
                                  {s}
                                </option>
                              ))}
                            </select>
                          </td>
                          <td className="p-2">
                            <Input
                              className="h-7 w-14 px-1"
                              type="number"
                              value={row.estimated_minutes}
                              onChange={(e) =>
                                patchDraft(j.id, {
                                  estimated_minutes: parseInt(e.target.value, 10) || 60,
                                })
                              }
                            />
                          </td>
                          <td className="p-2">
                            <Input
                              className="h-7 min-w-[88px] px-1"
                              value={(row.required_skills ?? []).join(", ")}
                              onChange={(e) =>
                                patchDraft(j.id, {
                                  required_skills: e.target.value
                                    .split(",")
                                    .map((s) => s.trim())
                                    .filter(Boolean),
                                })
                              }
                            />
                          </td>
                          <td className="p-2">
                            <Input
                              className="h-7 min-w-[88px] px-1"
                              value={(row.required_equipment ?? []).join(", ")}
                              onChange={(e) =>
                                patchDraft(j.id, {
                                  required_equipment: e.target.value
                                    .split(",")
                                    .map((s) => s.trim())
                                    .filter(Boolean),
                                })
                              }
                            />
                          </td>
                          <td className="p-2 whitespace-nowrap">
                            {dirty ? (
                              <Button size="sm" variant="secondary" className="h-7 text-xs" onClick={() => void saveRow(j.id)}>
                                Save
                              </Button>
                            ) : null}
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-7 text-xs text-destructive"
                              onClick={() => void removeRow(j.id)}
                            >
                              <Trash2 className="h-3 w-3" />
                            </Button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
              <div className="border-t p-2">
                <p className="text-muted-foreground mb-1 text-xs font-medium">Address (edit & save)</p>
                {jobs.map((j) => {
                  const row = getRow(j.id);
                  return (
                    <div key={`addr-${j.id}`} className="mb-2 flex gap-2">
                      <span className="w-24 shrink-0 font-mono text-xs">{j.id}</span>
                      <Input
                        className="h-8 flex-1 text-xs"
                        value={row.address}
                        onChange={(e) => patchDraft(j.id, { address: e.target.value })}
                      />
                      {drafts[j.id] ? (
                        <Button size="sm" className="h-8" onClick={() => void saveRow(j.id)}>
                          Save
                        </Button>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4 overflow-auto">
          {running ? (
            <div className="text-muted-foreground flex items-center gap-2 text-sm">
              <Loader2 className="h-5 w-5 animate-spin" />
              Running OR-Tools… (travel matrix + solver, ~30–60s)
            </div>
          ) : null}
          {result ? (
            <ScheduleGrid
              targetDate={result.target_date}
              routes={result.routes}
              crews={crews}
              jobs={jobsById}
              unassignedIds={result.unassigned_job_ids}
              messages={result.messages}
              status={result.status}
              durationSeconds={result.duration_seconds}
            />
          ) : (
            <Card>
              <CardContent className="text-muted-foreground p-8 text-center text-sm">
                Load jobs, edit if needed, then click <strong>Run optimizer</strong>. The schedule
                grid and diagnostics appear here.
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
