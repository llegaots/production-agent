"use client";

import { useMemo } from "react";
import { motion } from "framer-motion";
import { cn, seededRandom } from "@/lib/utils";
import { makeProjector } from "./projection";
import type { DoorPing, DoorOutcome, LatLng } from "@/lib/types";

const W = 800;
const H = 520;

/** Round to 2 decimals so SSR (Node Math.sin) and client (V8 Math.sin) emit
 *  identical SVG coordinate strings - avoids hydration mismatches. */
const r2 = (n: number) => Math.round(n * 100) / 100;

const outcomeStyle: Record<DoorOutcome, { fill: string; ring?: string; glow?: boolean }> = {
  lead: { fill: "#059e6e", ring: "#a7f3d0", glow: true },
  answered: { fill: "#34d399", ring: "#d1fae5" },
  callback: { fill: "#f5a623", ring: "#fff6e6" },
  "not-interested": { fill: "#fb7185", ring: "#fff1f3" },
  "no-answer": { fill: "#cbd3cf" },
};

export function VectorMap({
  path = [],
  trail = [],
  live = null,
  liveLabel,
  progress = 1,
  mode = "route",
  className,
}: {
  path?: LatLng[];
  trail?: DoorPing[];
  live?: LatLng | null;
  liveLabel?: string;
  progress?: number;
  mode?: "route" | "coverage";
  className?: string;
}) {
  const all = useMemo(
    () => [...path, ...trail.map((t) => t.position), ...(live ? [live] : [])],
    [path, trail, live],
  );

  const proj = useMemo(() => makeProjector(all.length ? all : [{ lat: 0, lng: 0 }], W, H), [all]);

  const routeD = useMemo(() => {
    if (path.length < 2) return "";
    return path
      .map((p) => {
        const { x, y } = proj.toXY(p);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .reduce((acc, pt, i) => (i === 0 ? `M${pt}` : `${acc} L${pt}`), "");
  }, [path, proj]);

  // decorative street grid
  const streets = useMemo(() => {
    const lines: { x1: number; y1: number; x2: number; y2: number; w: number }[] = [];
    for (let i = 0; i < 7; i++) {
      const y = 40 + ((H - 80) / 6) * i + seededRandom(i + 1) * 14;
      lines.push({ x1: 0, y1: r2(y), x2: W, y2: r2(y + (seededRandom(i + 9) - 0.5) * 30), w: i % 3 === 0 ? 2.2 : 1.2 });
    }
    for (let i = 0; i < 9; i++) {
      const x = 30 + ((W - 60) / 8) * i + seededRandom(i + 21) * 16;
      lines.push({ x1: r2(x), y1: 0, x2: r2(x + (seededRandom(i + 31) - 0.5) * 30), y2: H, w: i % 3 === 0 ? 2.2 : 1.2 });
    }
    return lines;
  }, []);

  const liveXY = live ? proj.toXY(live) : null;

  return (
    <div className={cn("relative overflow-hidden rounded-3xl bg-[#eef3f0]", className)}>
      {/* base tints */}
      <div className="absolute inset-0 bg-gradient-to-br from-[#eef5f1] via-[#eaf1ee] to-[#e6efe9]" />
      <div className="map-grid absolute inset-0 opacity-60" />
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(120%_90%_at_30%_10%,transparent_40%,rgba(13,23,19,0.06)_100%)]" />

      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="xMidYMid slice"
        className="relative h-full w-full"
      >
        <defs>
          <linearGradient id="route-grad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#34d399" />
            <stop offset="100%" stopColor="#059e6e" />
          </linearGradient>
          <filter id="route-glow" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="3" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* streets */}
        <g stroke="#ffffff" strokeOpacity="0.85" strokeLinecap="round">
          {streets.map((l, i) => (
            <line key={i} x1={l.x1} y1={l.y1} x2={l.x2} y2={l.y2} strokeWidth={l.w} />
          ))}
        </g>
        <g stroke="#d4ddd8" strokeOpacity="0.7" strokeLinecap="round">
          {streets.map((l, i) => (
            <line key={i} x1={l.x1} y1={l.y1} x2={l.x2} y2={l.y2} strokeWidth={Math.max(0.5, l.w - 1)} />
          ))}
        </g>

        {/* coverage blobs */}
        {mode === "coverage" &&
          trail.map((t) => {
            const { x, y } = proj.toXY(t.position);
            const good = t.outcome === "answered" || t.outcome === "lead";
            return (
              <circle
                key={`blob-${t.id}`}
                cx={x}
                cy={y}
                r={46}
                fill={good ? "#10b981" : "#f5a623"}
                opacity={0.1}
              />
            );
          })}

        {/* route underlay */}
        {routeD && (
          <path d={routeD} fill="none" stroke="#10b981" strokeOpacity="0.18" strokeWidth="11" strokeLinecap="round" strokeLinejoin="round" />
        )}

        {/* animated route (drawn portion) */}
        {routeD && (
          <motion.path
            d={routeD}
            fill="none"
            stroke="url(#route-grad)"
            strokeWidth="4.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            filter="url(#route-glow)"
            initial={{ pathLength: 0 }}
            animate={{ pathLength: Math.max(0.04, progress) }}
            transition={{ duration: 1.4, ease: [0.22, 1, 0.36, 1] }}
          />
        )}

        {/* door pings */}
        {trail.map((t, i) => {
          const x = r2(proj.toXY(t.position).x);
          const y = r2(proj.toXY(t.position).y);
          const s = outcomeStyle[t.outcome];
          return (
            <motion.g
              key={t.id}
              initial={{ opacity: 0, scale: 0 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: Math.min(i * 0.03, 0.6), type: "spring", stiffness: 380, damping: 22 }}
              style={{ transformOrigin: `${x}px ${y}px` }}
            >
              {s.ring && <circle cx={x} cy={y} r={7} fill={s.ring} opacity={0.9} />}
              <circle cx={x} cy={y} r={4} fill={s.fill} filter={s.glow ? "url(#route-glow)" : undefined} />
            </motion.g>
          );
        })}

        {/* live marker */}
        {liveXY && (
          <g>
            <motion.circle
              cx={r2(liveXY.x)}
              cy={r2(liveXY.y)}
              r={10}
              fill="#10b981"
              fillOpacity={0.25}
              animate={{ r: [10, 28], opacity: [0.4, 0] }}
              transition={{ duration: 1.8, repeat: Infinity, ease: "easeOut" }}
            />
            <circle cx={r2(liveXY.x)} cy={r2(liveXY.y)} r={9} fill="#ffffff" />
            <circle cx={r2(liveXY.x)} cy={r2(liveXY.y)} r={6} fill="#059e6e" filter="url(#route-glow)" />
          </g>
        )}
      </svg>

      {liveXY && liveLabel && (
        <div
          className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-[160%] whitespace-nowrap rounded-full bg-ink/90 px-2.5 py-1 text-[11px] font-semibold text-white shadow-lift backdrop-blur"
          style={{ left: `${r2((liveXY.x / W) * 100)}%`, top: `${r2((liveXY.y / H) * 100)}%` }}
        >
          {liveLabel}
        </div>
      )}

      {/* fallback badge */}
      <div className="pointer-events-none absolute bottom-3 right-3 rounded-lg bg-surface/80 px-2 py-1 text-[10px] font-medium text-faint backdrop-blur">
        Map preview · add Google key for satellite
      </div>
    </div>
  );
}
