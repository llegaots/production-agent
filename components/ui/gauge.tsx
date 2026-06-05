"use client";

import { motion } from "framer-motion";
import { cn, gradeLetter } from "@/lib/utils";

/** 270° radial gauge for a 0-100 grade. */
export function Gauge({
  value,
  size = 168,
  stroke = 14,
  showLetter = true,
  className,
}: {
  value: number;
  size?: number;
  stroke?: number;
  showLetter?: boolean;
  className?: string;
}) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const sweep = 0.75; // 270°
  const arc = c * sweep;
  const pct = Math.max(0, Math.min(100, value)) / 100;

  const color =
    value >= 90 ? "#10b981" : value >= 80 ? "#34d399" : value >= 70 ? "#f5a623" : "#f43f5e";

  return (
    <div className={cn("relative inline-grid place-items-center", className)} style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-[135deg]">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="var(--color-canvas-deep)"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${arc} ${c}`}
        />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${arc} ${c}`}
          initial={{ strokeDashoffset: arc }}
          animate={{ strokeDashoffset: arc * (1 - pct) }}
          transition={{ type: "spring", stiffness: 90, damping: 18 }}
          style={{ filter: `drop-shadow(0 0 8px ${color}55)` }}
        />
      </svg>
      <div className="absolute inset-0 grid place-items-center text-center">
        <div>
          <div className="nums text-4xl font-extrabold tracking-tight text-ink">{Math.round(value)}</div>
          {showLetter && (
            <div className="mt-0.5 text-xs font-semibold uppercase tracking-wide text-muted">
              Grade {gradeLetter(value)}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
