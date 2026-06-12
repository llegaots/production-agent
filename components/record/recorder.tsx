"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { AnimatePresence, motion } from "framer-motion";
import {
  Mic,
  Pause,
  Play,
  Square,
  CheckCircle2,
  AlertTriangle,
  ArrowLeftRight,
  MapPin,
  MapPinOff,
  Undo2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { MicWave } from "@/components/sessions/mic-wave";
import { cn } from "@/lib/utils";
import { LiveCapture, type CaptureStatus, type FinalLine } from "@/lib/voice/deepgram-live";
import { DwellTracker, type DoorVisit } from "@/lib/geo/dwell-tracker";

const FLUSH_MS = 1200; // debounce window for batching finalized lines to the server
const DISPLAY_CAP = 250; // keep the on-device transcript light over long shifts
const POSITION_POST_MS = 2000; // throttle live-location updates to the server (denser = fewer cut corners)

function clock(totalSec: number): string {
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = Math.floor(totalSec % 60);
  const pad = (n: number) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

type Phase = "ready" | "recording" | "paused" | "ended" | "error";

export function Recorder({
  sessionId,
  repName,
  territory,
}: {
  sessionId: string;
  repName: string;
  territory: string;
}) {
  const [phase, setPhase] = useState<Phase>("ready");
  const [elapsed, setElapsed] = useState(0);
  const [level, setLevel] = useState(0);
  const [lines, setLines] = useState<FinalLine[]>([]);
  const [interim, setInterim] = useState<{ text: string; speaker: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pinsOn, setPinsOn] = useState(true);
  const [lastPin, setLastPin] = useState<{ id: string; outcome: string } | null>(null);
  const pinTimer = useRef<number>(0);

  const captureRef = useRef<LiveCapture | null>(null);
  const pendingRef = useRef<FinalLine[]>([]);
  const flushTimer = useRef<number>(0);
  const wakeLock = useRef<WakeLockSentinel | null>(null);
  const scroller = useRef<HTMLDivElement | null>(null);
  const elapsedRef = useRef(0);
  const activeRef = useRef(false); // recording or paused - read by the pagehide handler
  // GPS / door tracking
  const trackerRef = useRef<DwellTracker | null>(null);
  const lastSeqRef = useRef(-1); // seq of the most recent finalized transcript line
  const doorFromSeqRef = useRef(0); // first transcript seq belonging to the open door
  const lastPosPostRef = useRef(0);

  // ── transcript persistence ──────────────────────────────────────────────────
  const flush = useCallback(async () => {
    const batch = pendingRef.current;
    if (!batch.length) return;
    pendingRef.current = [];
    try {
      await fetch(`/api/sessions/${sessionId}/transcript`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        keepalive: true,
        body: JSON.stringify({ lines: batch }),
      });
    } catch {
      // Re-queue on failure so a transient blip doesn't drop the lines.
      pendingRef.current = [...batch, ...pendingRef.current];
    }
  }, [sessionId]);

  const queueLine = useCallback(
    (line: FinalLine) => {
      pendingRef.current.push(line);
      if (flushTimer.current) window.clearTimeout(flushTimer.current);
      flushTimer.current = window.setTimeout(() => void flush(), FLUSH_MS);
    },
    [flush],
  );

  const uploadChunk = useCallback(
    (blob: Blob, seq: number) => {
      void fetch(`/api/sessions/${sessionId}/audio?seq=${seq}`, {
        method: "POST",
        headers: { "Content-Type": blob.type || "audio/webm" },
        keepalive: true,
        body: blob,
      }).catch(() => {});
    },
    [sessionId],
  );

  // ── GPS: live position (throttled) + door events ─────────────────────────────
  const postPosition = useCallback(
    (lat: number, lng: number) => {
      const now = Date.now();
      if (now - lastPosPostRef.current < POSITION_POST_MS) return;
      lastPosPostRef.current = now;
      void fetch(`/api/sessions/${sessionId}/position`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        keepalive: true,
        body: JSON.stringify({ lat, lng }),
      }).catch(() => {});
    },
    [sessionId],
  );

  const postDoor = useCallback(
    async (door: DoorVisit) => {
      const durationMs = new Date(door.endedAt).getTime() - new Date(door.startedAt).getTime();
      try {
        const res = await fetch(`/api/sessions/${sessionId}/doors`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          keepalive: true,
          body: JSON.stringify({
            lat: door.lat,
            lng: door.lng,
            accuracyM: door.accuracyM,
            durationMs,
            fromSeq: doorFromSeqRef.current,
            toSeq: lastSeqRef.current,
            at: door.startedAt,
          }),
        });
        const j = (await res.json().catch(() => ({}))) as { id?: string; outcome?: string };
        // Offer a quick undo (a street pause can still look like a door).
        if (res.ok && j.id) {
          setLastPin({ id: j.id, outcome: j.outcome ?? "no-answer" });
          if (pinTimer.current) window.clearTimeout(pinTimer.current);
          pinTimer.current = window.setTimeout(() => setLastPin(null), 7000);
        }
      } catch {
        /* never block capture */
      }
    },
    [sessionId],
  );

  // ── wake lock (best-effort; keeps the screen/mic alive while recording) ───────
  const acquireWakeLock = useCallback(async () => {
    try {
      if ("wakeLock" in navigator) {
        wakeLock.current = await navigator.wakeLock.request("screen");
      }
    } catch {
      /* not fatal */
    }
  }, []);

  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible" && phase === "recording") void acquireWakeLock();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [phase, acquireWakeLock]);

  // ── elapsed timer ─────────────────────────────────────────────────────────────
  useEffect(() => {
    if (phase !== "recording") return;
    const t = window.setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => window.clearInterval(t);
  }, [phase]);

  // auto-scroll transcript
  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [lines.length, interim]);

  // Keep refs current for the (once-bound) pagehide handler.
  useEffect(() => {
    elapsedRef.current = elapsed;
  }, [elapsed]);
  useEffect(() => {
    activeRef.current = phase === "recording" || phase === "paused";
  }, [phase]);

  // If the rep closes the tab or navigates away mid-session, end it server-side
  // so it doesn't linger as a "live" session forever.
  useEffect(() => {
    const onHide = () => {
      if (!activeRef.current) return;
      const body = new Blob([JSON.stringify({ durationSec: elapsedRef.current })], {
        type: "application/json",
      });
      navigator.sendBeacon?.(`/api/sessions/${sessionId}/end`, body);
      activeRef.current = false;
    };
    window.addEventListener("pagehide", onHide);
    return () => window.removeEventListener("pagehide", onHide);
  }, [sessionId]);

  const onStatus = useCallback((s: CaptureStatus) => {
    if (s === "recording") setPhase((p) => (p === "paused" ? p : "recording"));
  }, []);

  async function start() {
    setError(null);
    const capture = new LiveCapture({
      sessionId,
      onFinal: (line) => {
        lastSeqRef.current = line.seq;
        setLines((prev) => [...prev, line].slice(-DISPLAY_CAP));
        setInterim(null);
        queueLine(line);
      },
      onInterim: (text, speaker) => setInterim({ text, speaker }),
      onLevel: setLevel,
      onChunk: uploadChunk,
      onStatus,
      onError: (m) => {
        setError(m);
        setPhase("error");
      },
    });
    captureRef.current = capture;
    try {
      await capture.start();
      setPhase("recording");
      void acquireWakeLock();
      // Start GPS dwell tracking. Location is optional - if the rep denies it,
      // recording + transcript still work, just without the map pins.
      const tracker = new DwellTracker({
        onPosition: (lat, lng) => postPosition(lat, lng),
        onDoorOpen: () => {
          doorFromSeqRef.current = lastSeqRef.current + 1;
        },
        onDoorClose: (door) => postDoor(door),
        onError: () => {},
      });
      trackerRef.current = tracker;
      tracker.start();
    } catch {
      // onError already surfaced the message
    }
  }

  // Door detection is paused when recording is paused OR the rep turned pins off.
  const applyDwellPause = (recordingPaused: boolean, pins: boolean) =>
    trackerRef.current?.setPaused(recordingPaused || !pins);

  function togglePause() {
    const c = captureRef.current;
    if (!c) return;
    if (phase === "recording") {
      c.pause();
      applyDwellPause(true, pinsOn);
      setPhase("paused");
    } else if (phase === "paused") {
      c.resume();
      applyDwellPause(false, pinsOn);
      setPhase("recording");
    }
  }

  // Stop logging door pins (e.g. while resting on the street) without stopping
  // the recording / transcription.
  function togglePins() {
    const next = !pinsOn;
    setPinsOn(next);
    applyDwellPause(phase === "paused", next);
  }

  async function undoPin() {
    const p = lastPin;
    if (!p) return;
    setLastPin(null);
    if (pinTimer.current) window.clearTimeout(pinTimer.current);
    await fetch(`/api/sessions/${sessionId}/doors?id=${p.id}`, {
      method: "DELETE",
      keepalive: true,
    }).catch(() => {});
  }

  // If diarization labelled you as the prospect (or vice-versa), flip the mapping
  // for subsequent lines. Helps when the prospect happened to speak first.
  function swapSpeakers() {
    captureRef.current?.flipSpeakers();
  }

  async function end() {
    const c = captureRef.current;
    setPhase("ended");
    await c?.stop();
    if (flushTimer.current) window.clearTimeout(flushTimer.current);
    await flush();
    // Persist transcript first, then close GPS tracking so the final door's
    // classification can read its lines from the DB.
    trackerRef.current?.stop();
    await fetch(`/api/sessions/${sessionId}/end`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      keepalive: true,
      body: JSON.stringify({ durationSec: elapsed }),
    }).catch(() => {});
    wakeLock.current?.release().catch(() => {});
    wakeLock.current = null;
  }

  // best-effort cleanup if the component unmounts mid-session
  useEffect(() => {
    return () => {
      captureRef.current?.stop();
      trackerRef.current?.stop();
      wakeLock.current?.release().catch(() => {});
    };
  }, []);

  const recording = phase === "recording";
  const liveish = recording || phase === "paused";

  return (
    <main className="mx-auto flex min-h-dvh max-w-lg flex-col px-5 py-6">
      <header className="flex items-center justify-between">
        <div>
          <p className="font-display text-lg font-extrabold tracking-tight text-ink">{repName}</p>
          <p className="text-[13px] text-muted">{territory || "Live session"}</p>
        </div>
        {liveish && (
          <div className="flex items-center gap-2 rounded-full border border-line bg-surface px-3 py-1.5">
            <span
              className={cn(
                "size-2 rounded-full",
                recording ? "bg-primary-500 animate-[pulse-ring_2s_infinite]" : "bg-amber",
              )}
            />
            <span className="font-mono text-sm font-semibold tabular-nums text-ink">
              {clock(elapsed)}
            </span>
          </div>
        )}
      </header>

      {/* ── capture control ──────────────────────────────────────────────────── */}
      <section className="mt-6 flex flex-col items-center gap-4 rounded-3xl border border-line bg-surface p-6 shadow-card">
        {phase === "ready" && (
          <>
            <div className="grid size-20 place-items-center rounded-full bg-primary-50 text-primary-600">
              <Mic className="size-9" />
            </div>
            <p className="text-center text-sm text-muted">
              Keep this screen open while you knock. Your conversations transcribe live to your
              manager and leads are captured automatically.
            </p>
            <Button size="lg" className="w-full" onClick={start}>
              <Mic className="size-4" /> Start recording
            </Button>
          </>
        )}

        {liveish && (
          <>
            <MicWave level={recording ? level : 0} bars={28} className="h-10" />
            <div className="flex w-full gap-3">
              <Button variant="secondary" size="lg" className="flex-1" onClick={togglePause}>
                {recording ? <Pause className="size-4" /> : <Play className="size-4" />}
                {recording ? "Pause" : "Resume"}
              </Button>
              <Button variant="danger" size="lg" className="flex-1" onClick={end}>
                <Square className="size-4" /> End session
              </Button>
            </div>
            <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1.5">
              <button
                onClick={swapSpeakers}
                className="inline-flex items-center gap-1.5 text-[12px] font-medium text-muted transition-colors hover:text-ink"
              >
                <ArrowLeftRight className="size-3.5" /> Swap speaker labels (me ↔ prospect)
              </button>
              <button
                onClick={togglePins}
                className={cn(
                  "inline-flex items-center gap-1.5 text-[12px] font-medium transition-colors",
                  pinsOn ? "text-muted hover:text-ink" : "text-[#b45309]",
                )}
              >
                {pinsOn ? <MapPin className="size-3.5" /> : <MapPinOff className="size-3.5" />}
                {pinsOn ? "Door pins on" : "Door pins paused"}
              </button>
            </div>
          </>
        )}

        {phase === "ended" && (
          <>
            <div className="grid size-20 place-items-center rounded-full bg-primary-50 text-primary-600">
              <CheckCircle2 className="size-9" />
            </div>
            <p className="text-center text-sm text-muted">
              Session saved - {clock(elapsed)} recorded. Your manager has the full transcript.
            </p>
            <Button size="lg" className="w-full" asChild>
              <Link href="/record">Start another session</Link>
            </Button>
          </>
        )}

        {phase === "error" && (
          <>
            <div className="grid size-20 place-items-center rounded-full bg-rose-50 text-[#be123c]">
              <AlertTriangle className="size-9" />
            </div>
            <p className="text-center text-sm text-[#be123c]">{error}</p>
            <Button variant="secondary" size="lg" className="w-full" onClick={() => setPhase("ready")}>
              Try again
            </Button>
          </>
        )}
      </section>

      {liveish && lastPin && (
        <div className="mt-3 flex items-center justify-between gap-2 rounded-2xl border border-line bg-surface-muted px-4 py-2.5 text-[13px]">
          <span className="text-muted">
            Logged a {lastPin.outcome === "no-answer" ? "no-answer" : lastPin.outcome} at this spot.
          </span>
          <button
            onClick={undoPin}
            className="inline-flex items-center gap-1 font-semibold text-[#be123c] hover:underline"
          >
            <Undo2 className="size-3.5" /> Not a door, undo
          </button>
        </div>
      )}

      {/* ── live transcript (rep's own view) ─────────────────────────────────── */}
      {liveish && (
        <div
          ref={scroller}
          className="mt-5 flex-1 space-y-2 overflow-y-auto rounded-3xl border border-line bg-surface p-4"
        >
          {lines.length === 0 && !interim && (
            <p className="py-8 text-center text-sm text-muted">Listening…</p>
          )}
          <AnimatePresence initial={false}>
            {lines.map((l) => (
              <motion.div
                key={`${l.seq}-${l.at}`}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                className={cn("flex", l.speaker === "rep" ? "justify-end" : "justify-start")}
              >
                <span
                  className={cn(
                    "max-w-[85%] rounded-2xl px-3 py-2 text-[13px] leading-snug",
                    l.speaker === "rep"
                      ? "bg-primary-50 text-primary-800"
                      : "bg-canvas-deep text-ink",
                  )}
                >
                  {l.text}
                </span>
              </motion.div>
            ))}
          </AnimatePresence>
          {interim && (
            <div
              className={cn("flex", interim.speaker === "rep" ? "justify-end" : "justify-start")}
            >
              <span className="max-w-[85%] rounded-2xl px-3 py-2 text-[13px] italic leading-snug text-faint">
                {interim.text}
              </span>
            </div>
          )}
        </div>
      )}
    </main>
  );
}
