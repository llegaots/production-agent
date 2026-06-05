"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { Sparkles, Send, Check, X, Loader2, Users, DoorOpen, Clock, MapPin, Wand2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CoverageMap, type CoverageRoute } from "@/components/maps/coverage-map";
import { cn } from "@/lib/utils";
import { fadeInUp, staggerContainer } from "@/lib/motion";
import type { RoutePreview } from "@/lib/types";

const PALETTE = ["#059e6e", "#2563eb", "#d97706", "#7c3aed", "#dc2626", "#0891b2"];
const TORONTO = { lat: 43.6629, lng: -79.3957 };

const SUGGESTIONS = ["Make the routes a bit bigger", "Shift coverage east", "Trim them — too long"];

export function RoutePreviewPanel({
  genId,
  onClose,
}: {
  genId: string;
  onClose: () => void;
}) {
  const router = useRouter();
  const [preview, setPreview] = useState<RoutePreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [err, setErr] = useState("");
  const [hover, setHover] = useState<string | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(`/api/routes/generations/${genId}`, { cache: "no-store" });
        const j = await r.json();
        setPreview(j.generation?.preview ?? null);
      } finally {
        setLoading(false);
      }
    })();
  }, [genId]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [preview?.chat.length, sending]);

  const send = async (msg: string) => {
    const text = msg.trim();
    if (!text || sending) return;
    setInput("");
    setErr("");
    // optimistic user turn
    setPreview((p) => (p ? { ...p, chat: [...p.chat, { role: "user", text }] } : p));
    setSending(true);
    try {
      const r = await fetch(`/api/routes/generations/${genId}/refine`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ message: text }),
      });
      const j = await r.json();
      if (!r.ok) {
        setErr(j.error ?? "Refine failed");
        setPreview((p) => (p ? { ...p, chat: p.chat.slice(0, -1) } : p)); // roll back optimistic
      } else {
        setPreview(j.preview);
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Network error");
    } finally {
      setSending(false);
    }
  };

  const confirm = async () => {
    setConfirming(true);
    setErr("");
    try {
      const r = await fetch(`/api/routes/generations/${genId}/confirm`, { method: "POST" });
      const j = await r.json();
      if (!r.ok) {
        setErr(j.error ?? "Could not schedule");
        setConfirming(false);
        return;
      }
      router.refresh();
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Network error");
      setConfirming(false);
    }
  };

  const routes = preview?.routes ?? [];
  const coverageRoutes: CoverageRoute[] = routes
    .filter((r) => r.path.length > 1)
    .map((r, i) => ({ id: r.tempId, name: r.name, path: r.path, color: PALETTE[i % PALETTE.length] }));
  const center = routes[0]?.center ?? TORONTO;
  const totalDoors = routes.reduce((s, r) => s + r.doors, 0);

  return (
    <div className="mx-auto flex max-w-[1500px] flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <span className="grid size-9 place-items-center rounded-2xl bg-primary-100 text-primary-700">
            <Wand2 className="size-5" />
          </span>
          <div>
            <h3 className="text-base font-bold tracking-tight text-ink">Route preview</h3>
            <p className="text-[12px] text-muted">
              {preview ? `${routes.length} route${routes.length === 1 ? "" : "s"} · ${totalDoors} doors · not scheduled yet` : "Loading…"}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={onClose} disabled={confirming}>
            <X className="size-4" /> Discard
          </Button>
          <Button size="sm" onClick={confirm} disabled={confirming || !routes.length}>
            {confirming ? <Loader2 className="size-4 animate-spin" /> : <Check className="size-4" />}
            Confirm & schedule
          </Button>
        </div>
      </div>

      {err && (
        <div className="rounded-2xl border border-rose-100 bg-rose-50/60 px-4 py-2.5 text-[12.5px] text-[#be123c]">{err}</div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_380px]">
        {/* map + route cards */}
        <div className="flex flex-col gap-3">
          <div className="relative h-[460px] overflow-hidden rounded-3xl border border-line shadow-card">
            {loading ? (
              <div className="grid h-full place-items-center text-[13px] text-muted">
                <Loader2 className="size-5 animate-spin text-primary-500" />
              </div>
            ) : (
              <CoverageMap key={routes.map((r) => r.tempId).join("-")} routes={coverageRoutes} center={center} highlightId={hover} className="h-full" />
            )}
          </div>
          <motion.div variants={staggerContainer(0.05)} initial="hidden" animate="show" className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {routes.map((r, i) => (
              <motion.div
                key={r.tempId}
                variants={fadeInUp}
                onMouseEnter={() => setHover(r.tempId)}
                onMouseLeave={() => setHover(null)}
                className={cn(
                  "rounded-2xl border p-3.5 transition-colors",
                  hover === r.tempId ? "border-primary-200 bg-primary-50/40" : "border-line bg-surface",
                )}
              >
                <div className="flex items-start gap-2.5">
                  <span className="mt-1 size-3 shrink-0 rounded-full" style={{ backgroundColor: PALETTE[i % PALETTE.length] }} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[13px] font-semibold text-ink">{r.name}</div>
                    <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px] text-muted">
                      <span className="inline-flex items-center gap-1"><DoorOpen className="size-3" /> {r.doors} doors</span>
                      <span className="inline-flex items-center gap-1"><Clock className="size-3" /> ~{r.minutes}m</span>
                      <span className="inline-flex items-center gap-1"><Users className="size-3" /> {r.marketerNames.join(" & ")}</span>
                    </div>
                  </div>
                </div>
              </motion.div>
            ))}
          </motion.div>
        </div>

        {/* chat */}
        <div className="flex h-[640px] flex-col rounded-3xl border border-line bg-surface shadow-card">
          <div className="flex items-center gap-2 border-b border-line px-4 py-3">
            <Sparkles className="size-4 text-primary-600" />
            <div>
              <div className="text-[13px] font-bold text-ink">Refine with AI</div>
              <div className="text-[11px] text-muted">Tell it what to change, then confirm</div>
            </div>
          </div>

          <div className="flex-1 space-y-3 overflow-y-auto p-4 pretty-scroll">
            {(preview?.chat ?? []).map((c, i) => (
              <div key={i} className={cn("flex", c.role === "user" ? "justify-end" : "justify-start")}>
                <div
                  className={cn(
                    "max-w-[85%] rounded-2xl px-3 py-2 text-[12.5px] leading-relaxed",
                    c.role === "user"
                      ? "bg-primary-600 text-white"
                      : "border border-line bg-surface-muted/60 text-ink-soft",
                  )}
                >
                  {c.text}
                </div>
              </div>
            ))}
            {sending && (
              <div className="flex justify-start">
                <div className="inline-flex items-center gap-2 rounded-2xl border border-line bg-surface-muted/60 px-3 py-2 text-[12px] text-muted">
                  <Loader2 className="size-3.5 animate-spin" /> Re-planning…
                </div>
              </div>
            )}
            <div ref={chatEndRef} />
          </div>

          {preview && (preview.chat?.length ?? 0) <= 1 && (
            <div className="flex flex-wrap gap-1.5 px-4 pb-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => send(s)}
                  disabled={sending}
                  className="rounded-full border border-line bg-surface px-2.5 py-1 text-[11px] font-medium text-ink-soft transition-colors hover:bg-surface-muted disabled:opacity-50"
                >
                  {s}
                </button>
              ))}
            </div>
          )}

          <form
            onSubmit={(e) => {
              e.preventDefault();
              send(input);
            }}
            className="flex items-center gap-2 border-t border-line p-3"
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="e.g. cover Main St instead…"
              disabled={sending || confirming}
              className="h-10 flex-1 rounded-xl border border-line bg-surface px-3 text-[13px] text-ink outline-none placeholder:text-faint focus:border-primary-300 focus:ring-2 focus:ring-primary-100 disabled:opacity-50"
            />
            <Button type="submit" size="sm" disabled={!input.trim() || sending || confirming}>
              <Send className="size-4" />
            </Button>
          </form>
        </div>
      </div>

      <p className="flex items-center gap-1.5 text-center text-[11px] text-faint">
        <MapPin className="size-3" /> Confirming creates these routes and links them to each crew&apos;s shift on the planned date.
      </p>
    </div>
  );
}
