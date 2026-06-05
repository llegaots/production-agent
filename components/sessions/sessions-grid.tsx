"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { DoorOpen, Sparkles, Users, RadioTower } from "lucide-react";
import type { RealtimePostgresInsertPayload, RealtimePostgresUpdatePayload } from "@supabase/supabase-js";
import { SessionCard } from "./session-card";
import { DemoButton } from "./demo-button";
import { EmptyState } from "@/components/ui/empty-state";
import { supabaseBrowser } from "@/lib/supabase/client";
import { staggerContainer, fadeInUp } from "@/lib/motion";
import type { LatLng, Session, Speaker, TranscriptLine } from "@/lib/types";

type Row = Record<string, unknown>;
type LinesMap = Record<string, TranscriptLine[]>;

export function SessionsGrid({
  sessions: initialSessions,
  initialLines = {},
}: {
  sessions: Session[];
  initialLines?: LinesMap;
}) {
  const router = useRouter();
  const [sessions, setSessions] = useState<Session[]>(initialSessions);
  const [lines, setLines] = useState<LinesMap>(initialLines);

  // Re-seed from the server on each re-render (new/removed live sessions, fresh
  // baseline metrics). Render-phase sync keyed on the server prop's identity.
  const [syncedTo, setSyncedTo] = useState(initialSessions);
  if (syncedTo !== initialSessions) {
    setSyncedTo(initialSessions);
    setSessions(initialSessions);
    setLines(initialLines);
  }

  // Keep the live-session id set in a ref so the realtime subscription can read
  // it without re-subscribing on every metric tick.
  const liveIdsRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    liveIdsRef.current = new Set(sessions.map((s) => s.id));
  }, [sessions]);

  useEffect(() => {
    const db = supabaseBrowser();
    if (!db) return;
    const channel = db
      .channel("sessions-grid")
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "D2D_TranscriptLines" },
        (p: RealtimePostgresInsertPayload<Row>) => {
          const sid = p.new.session_id as string;
          if (!liveIdsRef.current.has(sid)) return;
          const line: TranscriptLine = {
            id: p.new.id as string,
            at: (p.new.at as string) ?? (p.new.created_at as string),
            speaker: (p.new.speaker as Speaker) ?? "prospect",
            text: (p.new.text as string) ?? "",
          };
          setLines((prev) => {
            const cur = prev[sid] ?? [];
            if (cur.some((l) => l.id === line.id)) return prev;
            return { ...prev, [sid]: [...cur, line].slice(-6) };
          });
        },
      )
      .on(
        "postgres_changes",
        { event: "UPDATE", schema: "public", table: "D2D_Sessions" },
        (p: RealtimePostgresUpdatePayload<Row>) => {
          const id = p.new.id as string;
          if (p.new.status && p.new.status !== "live") {
            router.refresh(); // a rep finished - drop them from the live grid
            return;
          }
          setSessions((prev) =>
            prev.map((s) =>
              s.id === id
                ? {
                    ...s,
                    doors: (p.new.doors as number) ?? s.doors,
                    conversations: (p.new.conversations as number) ?? s.conversations,
                    leads: (p.new.leads as number) ?? s.leads,
                    noAnswers: (p.new.no_answers as number) ?? s.noAnswers,
                    grade: (p.new.grade as number) ?? s.grade,
                    position:
                      typeof p.new.lat === "number" && typeof p.new.lng === "number"
                        ? { lat: p.new.lat as number, lng: p.new.lng as number }
                        : s.position,
                    // Prefer the persisted trail; else grow it from the live point
                    // so the trace shows even before migration 0010 is applied.
                    trailPath: Array.isArray(p.new.trail_path)
                      ? (p.new.trail_path as typeof s.trailPath)
                      : typeof p.new.lat === "number" && typeof p.new.lng === "number"
                        ? [...(s.trailPath ?? []), { lat: p.new.lat as number, lng: p.new.lng as number }].slice(-1500)
                        : s.trailPath,
                  }
                : s,
            ),
          );
        },
      )
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "D2D_Sessions" },
        () => router.refresh(), // a rep went live - pull the hydrated row in
      )
      .subscribe();
    return () => {
      void db.removeChannel(channel);
    };
  }, [router]);

  // Reliable trace fallback: poll positions + trails for the live cards over HTTP
  // (so the dot moves and the trace grows even if Realtime UPDATE events are flaky).
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await fetch("/api/sessions/live-positions", { cache: "no-store" });
        if (!r.ok || !alive) return;
        const j = (await r.json()) as {
          sessions: { id: string; lat: number | null; lng: number | null; trailPath: LatLng[] }[];
        };
        const byId = new Map(j.sessions.map((s) => [s.id, s]));
        setSessions((prev) =>
          prev.map((s) => {
            const u = byId.get(s.id);
            if (!u) return s;
            const pos = typeof u.lat === "number" && typeof u.lng === "number" ? { lat: u.lat, lng: u.lng } : s.position;
            let trailPath = s.trailPath ?? [];
            if (u.trailPath.length > 1) trailPath = u.trailPath;
            else if (typeof u.lat === "number" && typeof u.lng === "number") {
              const last = trailPath[trailPath.length - 1];
              if (!last || Math.abs(last.lat - u.lat) > 1e-6 || Math.abs(last.lng - u.lng) > 1e-6) {
                trailPath = [...trailPath, { lat: u.lat, lng: u.lng }].slice(-1500);
              }
            }
            return { ...s, position: pos, trailPath };
          }),
        );
      } catch {
        /* keep polling */
      }
    };
    void tick();
    const iv = setInterval(tick, 1500);
    return () => {
      alive = false;
      clearInterval(iv);
    };
  }, []);

  if (sessions.length === 0) {
    return (
      <div className="mx-auto max-w-[1400px]">
        <div className="rounded-3xl border border-line bg-surface shadow-card">
          <EmptyState
            icon={<RadioTower className="size-6" />}
            title="No reps live right now"
            description="When a marketer starts a field session, they appear here in real time, with live transcript, AI grade, detected leads and their route drawing on the map. Or press Start live demo to see it in action."
            action={<DemoButton />}
          />
        </div>
      </div>
    );
  }

  const totalDoors = sessions.reduce((a, s) => a + s.doors, 0);
  const totalLeads = sessions.reduce((a, s) => a + s.leads, 0);
  const summary = [
    { label: "Reps live now", value: sessions.length, icon: Users, chip: "bg-primary-50 text-primary-700" },
    { label: "Doors this shift", value: totalDoors, icon: DoorOpen, chip: "bg-sky-50 text-[#0284c7]" },
    { label: "Leads captured", value: totalLeads, icon: Sparkles, chip: "bg-violet-50 text-[#6d28d9]" },
  ];

  return (
    <div className="mx-auto flex max-w-[1400px] flex-col gap-5">
      <motion.div
        variants={staggerContainer(0.07)}
        initial="hidden"
        animate="show"
        className="grid grid-cols-1 gap-3 sm:grid-cols-3"
      >
        {summary.map((s) => (
          <motion.div
            key={s.label}
            variants={fadeInUp}
            className="flex items-center gap-3 rounded-3xl border border-line bg-surface px-5 py-4 shadow-card"
          >
            <span className={`grid size-11 place-items-center rounded-2xl ${s.chip}`}>
              <s.icon className="size-5" />
            </span>
            <div>
              <div className="nums text-2xl font-extrabold tracking-tight text-ink">{s.value}</div>
              <div className="text-[12px] text-muted">{s.label}</div>
            </div>
          </motion.div>
        ))}
      </motion.div>

      <div>
        <h3 className="mb-3 px-1 text-sm font-semibold text-ink-soft">
          Active sessions · click any rep to watch live
        </h3>
        <motion.div
          variants={staggerContainer(0.08)}
          initial="hidden"
          animate="show"
          className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3"
        >
          {sessions.map((s) => (
            <SessionCard key={s.id} session={s} latestLines={lines[s.id]} />
          ))}
        </motion.div>
      </div>
    </div>
  );
}
