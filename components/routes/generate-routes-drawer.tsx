"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { Sparkles, CheckCircle2, AlertTriangle, Loader2, Users } from "lucide-react";
import { Drawer } from "@/components/ui/drawer";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Avatar } from "@/components/ui/avatar";
import { Progress } from "@/components/ui/progress";
import { PostalAutocomplete, type PostalPlace } from "./postal-autocomplete";
import { cn } from "@/lib/utils";
import { ymd } from "@/lib/calendar";
import type { Rep, Shift } from "@/lib/types";

type MState = { included: boolean; start: string; end: string };
type Phase = "form" | "running" | "done" | "error";

const STEPS = ["Geocoding area", "Fetching homes & streets", "Checking past coverage", "Planning routes", "Building preview"];

export function GenerateRoutesDrawer({
  open,
  onOpenChange,
  reps,
  shifts,
  teamId,
  onPreview,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  reps: Rep[];
  shifts: Shift[];
  teamId: string | null;
  onPreview?: (genId: string) => void;
}) {
  const router = useRouter();
  const [area, setArea] = useState("");
  const [place, setPlace] = useState<PostalPlace | null>(null);
  const [date, setDate] = useState(() => ymd(new Date()));
  const [sessionHours, setSessionHours] = useState(4);
  const [minPerDoor, setMinPerDoor] = useState(2);
  const [walkKmh, setWalkKmh] = useState(4.5);
  const [avoidDays, setAvoidDays] = useState(60);
  const buildMState = () => {
    const map: Record<string, MState> = {};
    for (const rep of reps) {
      const shift = shifts.find((s) => s.repId === rep.id && s.date === date);
      map[rep.id] = shift
        ? { included: true, start: shift.start, end: shift.end }
        : { included: false, start: "16:00", end: "21:00" };
    }
    return map;
  };
  const [mstate, setMstate] = useState<Record<string, MState>>(buildMState);
  const [phase, setPhase] = useState<Phase>("form");
  const [stage, setStage] = useState("");
  const [progress, setProgress] = useState(0);
  const [summary, setSummary] = useState("");
  const [error, setError] = useState("");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // rebuild the per-marketer map when the date changes or the drawer reopens, and
  // reset the wizard whenever it opens, all without a synchronous effect
  const [sync, setSync] = useState({ open, date });
  if (sync.open !== open || sync.date !== date) {
    const justOpened = open && !sync.open;
    setSync({ open, date });
    setMstate(buildMState());
    if (justOpened) {
      setPhase("form");
      setError("");
      setSummary("");
      setProgress(0);
    }
  }

  // keep the poll timer tidy: stop it when the drawer closes or unmounts
  useEffect(() => {
    if (!open && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [open]);

  const included = reps.filter((r) => mstate[r.id]?.included);
  const pairs = Math.floor(included.length / 2);
  const canRun = area.trim().length > 1 && included.length >= 2 && phase === "form";

  const setM = (id: string, patch: Partial<MState>) =>
    setMstate((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } }));

  async function generate() {
    setPhase("running");
    setProgress(8);
    setStage("Starting");
    setError("");
    const marketers = included.map((r) => ({
      id: r.id,
      name: r.name,
      territory: r.territory,
      start: mstate[r.id].start,
      end: mstate[r.id].end,
    }));
    let json: { generationId?: string; error?: string };
    try {
      const res = await fetch("/api/routes/generate", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          area: area.trim(),
          date,
          sessionHours,
          minPerDoor,
          walkKmh,
          avoidDays,
          teamId,
          marketers,
          // coordinates from the picked place, so the server skips geocoding a
          // bare postal code (which OSM often can't resolve for Canadian FSAs)
          center: place ? { lat: place.lat, lng: place.lng } : undefined,
          bounds: place?.bounds,
        }),
      });
      json = await res.json();
      if (!res.ok) {
        setError(json.error ?? "Failed to start generation");
        setPhase("error");
        return;
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Network error");
      setPhase("error");
      return;
    }

    const id = json.generationId!;
    pollRef.current = setInterval(async () => {
      try {
        const r = await fetch(`/api/routes/generations/${id}`, { cache: "no-store" });
        const j = await r.json();
        const g = j.generation;
        if (!g) return;
        setStage(g.stage);
        setProgress(g.progress);
        if (g.status === "preview" || g.status === "done") {
          if (pollRef.current) clearInterval(pollRef.current);
          setSummary(g.agentSummary ?? "");
          if (onPreview) {
            onOpenChange(false);
            onPreview(id);
          } else {
            setPhase("done");
            router.refresh();
          }
        } else if (g.status === "error") {
          if (pollRef.current) clearInterval(pollRef.current);
          setError(g.error ?? "Generation failed");
          setPhase("error");
        }
      } catch {
        /* keep polling */
      }
    }, 1500);
  }

  return (
    <Drawer
      open={open}
      onOpenChange={onOpenChange}
      title="Generate routes with AI"
      description="The planner maps streets, pairs marketers, and avoids past coverage"
      widthClass="max-w-lg"
    >
      {phase === "form" && (
        <div className="flex flex-col gap-5 p-6">
          <label className="block">
            <span className="mb-1.5 block text-[12px] font-medium text-ink-soft">Postal code to market</span>
            <PostalAutocomplete
              value={area}
              onChange={(t) => {
                setArea(t);
                setPlace(null); // typed, not picked - fall back to geocoding
              }}
              onSelect={(p) => {
                setArea(p.area);
                setPlace(p);
              }}
              placeholder="Search an address or area, or type a postal code…"
            />
            <p className="mt-1.5 text-[11px] text-faint">
              {place
                ? `Pinned to ${place.label}. Routes will be generated around this area.`
                : "Pick a suggestion to pin the exact spot. Use the 3-character area (e.g. M4M) to cover the whole zone, or a full code to stay tight."}
            </p>
          </label>

          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="mb-1.5 block text-[12px] font-medium text-ink-soft">Date</span>
              <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
            </label>
            <label className="block">
              <span className="mb-1.5 block text-[12px] font-medium text-ink-soft">Session length (hrs)</span>
              <Input type="number" step="0.5" min="0.5" value={sessionHours} onChange={(e) => setSessionHours(Number(e.target.value))} />
            </label>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="mb-1.5 block text-[12px] font-medium text-ink-soft">Avg min / door</span>
              <Input type="number" step="0.5" value={minPerDoor} onChange={(e) => setMinPerDoor(Number(e.target.value))} />
            </label>
            <label className="block">
              <span className="mb-1.5 block text-[12px] font-medium text-ink-soft">Walking speed (km/h)</span>
              <Input type="number" step="0.5" value={walkKmh} onChange={(e) => setWalkKmh(Number(e.target.value))} />
            </label>
          </div>
          <p className="-mt-2 text-[11px] text-faint">
            Each route is a loop sized to the session - real homes (knock time) + walking - back to the meet point.
          </p>

          <label className="block">
            <span className="mb-1.5 block text-[12px] font-medium text-ink-soft">
              Avoid streets covered in the last {avoidDays} days
            </span>
            <input
              type="range"
              min={0}
              max={120}
              step={15}
              value={avoidDays}
              onChange={(e) => setAvoidDays(Number(e.target.value))}
              className="w-full accent-primary-500"
            />
          </label>

          <div>
            <div className="mb-2 flex items-center justify-between">
              <span className="text-[12px] font-medium text-ink-soft">Marketers on shift</span>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-primary-50 px-2 py-0.5 text-[11px] font-bold text-primary-700">
                <Users className="size-3" /> {included.length} → {pairs} route{pairs === 1 ? "" : "s"}
              </span>
            </div>
            {reps.length === 0 && (
              <p className="rounded-2xl border border-dashed border-line bg-surface-muted/60 px-3 py-3 text-[12px] text-muted">
                No marketers found. Apply the Supabase migrations to seed the team.
              </p>
            )}
            <div className="flex flex-col gap-1.5">
              {reps.map((rep) => {
                const m = mstate[rep.id];
                if (!m) return null;
                return (
                  <div
                    key={rep.id}
                    className={cn(
                      "flex items-center gap-2.5 rounded-2xl border px-3 py-2 transition-colors",
                      m.included ? "border-primary-200 bg-primary-50/40" : "border-line",
                    )}
                  >
                    <button
                      onClick={() => setM(rep.id, { included: !m.included })}
                      className={cn(
                        "grid size-5 shrink-0 place-items-center rounded-md border transition-colors",
                        m.included ? "border-primary-500 bg-primary-500 text-white" : "border-line bg-surface",
                      )}
                    >
                      {m.included && <CheckCircle2 className="size-3.5" />}
                    </button>
                    <Avatar name={rep.name} tint={rep.avatarTint} size="sm" />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[13px] font-semibold text-ink">{rep.name}</div>
                      <div className="truncate text-[11px] text-muted">{rep.territory || "-"}</div>
                    </div>
                    <input
                      type="time"
                      value={m.start}
                      disabled={!m.included}
                      onChange={(e) => setM(rep.id, { start: e.target.value })}
                      className="h-8 rounded-lg border border-line bg-surface px-1.5 text-[12px] text-ink disabled:opacity-40"
                    />
                    <span className="text-faint">-</span>
                    <input
                      type="time"
                      value={m.end}
                      disabled={!m.included}
                      onChange={(e) => setM(rep.id, { end: e.target.value })}
                      className="h-8 rounded-lg border border-line bg-surface px-1.5 text-[12px] text-ink disabled:opacity-40"
                    />
                  </div>
                );
              })}
            </div>
            {included.length % 2 === 1 && included.length >= 1 && (
              <p className="mt-2 text-[11px] text-[#b45309]">
                Odd number selected - the planner will fold the extra marketer into a nearby pair (no one walks alone).
              </p>
            )}
          </div>

          <div className="flex gap-2 pt-1">
            <Button className="flex-1" disabled={!canRun} onClick={generate}>
              <Sparkles className="size-4" /> Generate {pairs} route{pairs === 1 ? "" : "s"}
            </Button>
            <Button variant="secondary" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
          </div>
        </div>
      )}

      {phase === "running" && (
        <div className="flex flex-col gap-5 p-6">
          <div className="flex items-center gap-3 rounded-2xl border border-primary-100 bg-primary-50/50 p-4">
            <Loader2 className="size-5 animate-spin text-primary-600" />
            <div className="min-w-0">
              <div className="text-sm font-semibold text-ink">{stage || "Working…"}</div>
              <div className="text-[12px] text-muted">Planning {pairs} route{pairs === 1 ? "" : "s"} for {area}</div>
            </div>
          </div>
          <Progress value={progress} />
          <ol className="flex flex-col gap-1.5">
            {STEPS.map((s) => {
              const idx = STEPS.indexOf(s);
              const curIdx = STEPS.findIndex((x) => x === stage);
              const state = curIdx > idx ? "done" : curIdx === idx ? "active" : "todo";
              return (
                <li key={s} className="flex items-center gap-2.5 text-[13px]">
                  <span
                    className={cn(
                      "grid size-5 place-items-center rounded-full text-[10px] font-bold",
                      state === "done" && "bg-primary-500 text-white",
                      state === "active" && "bg-primary-100 text-primary-700",
                      state === "todo" && "bg-canvas-deep text-faint",
                    )}
                  >
                    {state === "done" ? "✓" : idx + 1}
                  </span>
                  <span className={cn(state === "todo" ? "text-faint" : "text-ink-soft")}>{s}</span>
                  {state === "active" && <Loader2 className="size-3 animate-spin text-primary-600" />}
                </li>
              );
            })}
          </ol>
          <p className="text-[11px] text-faint">
            This can take 20-60s - geocoding, pulling the street network from OpenStreetMap, then planning.
          </p>
        </div>
      )}

      {phase === "done" && (
        <div className="flex flex-col gap-5 p-6">
          <motion.div
            initial={{ scale: 0.9, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            className="flex items-center gap-3 rounded-2xl border border-primary-100 bg-gradient-to-br from-primary-50/70 to-surface p-4"
          >
            <CheckCircle2 className="size-6 text-primary-600" />
            <div className="text-sm font-semibold text-ink">Routes generated</div>
          </motion.div>
          {summary && <p className="text-[13px] leading-relaxed text-ink-soft">{summary}</p>}
          <Button onClick={() => onOpenChange(false)}>View routes</Button>
        </div>
      )}

      {phase === "error" && (
        <div className="flex flex-col gap-5 p-6">
          <div className="flex items-start gap-3 rounded-2xl border border-rose-50 bg-rose-50/60 p-4">
            <AlertTriangle className="mt-0.5 size-5 shrink-0 text-[#be123c]" />
            <div>
              <div className="text-sm font-semibold text-ink">Couldn&apos;t generate routes</div>
              <p className="mt-1 text-[12px] leading-relaxed text-ink-soft">{error}</p>
            </div>
          </div>
          <Button variant="secondary" onClick={() => setPhase("form")}>
            Back
          </Button>
        </div>
      )}
    </Drawer>
  );
}
