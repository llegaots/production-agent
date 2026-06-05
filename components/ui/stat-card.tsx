"use client";

import { motion } from "framer-motion";
import { ArrowUpRight, ArrowDownRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { fadeInUp } from "@/lib/motion";
import { tints } from "./tint";
import { AnimatedNumber } from "./animated-number";
import type { AccentTint } from "@/lib/types";

export function StatCard({
  label,
  value,
  suffix,
  hint,
  delta,
  tint,
  icon,
  decimals = 0,
}: {
  label: string;
  value: number;
  suffix?: string;
  hint: string;
  delta?: number;
  tint: AccentTint;
  icon: React.ReactNode;
  decimals?: number;
}) {
  const t = tints[tint];
  const up = (delta ?? 0) >= 0;

  return (
    <motion.div
      variants={fadeInUp}
      whileHover={{ y: -4 }}
      transition={{ type: "spring", stiffness: 380, damping: 26 }}
      className={cn(
        "group relative overflow-hidden rounded-3xl border border-line bg-gradient-to-br p-5 shadow-card",
        t.card,
      )}
    >
      {/* decorative glow */}
      <div className={cn("pointer-events-none absolute -right-8 -top-10 size-28 rounded-full opacity-40 blur-2xl", t.solid)} />

      <div className="relative flex items-start justify-between">
        <span className="text-[13px] font-medium text-ink-soft">{label}</span>
        <span
          className={cn(
            "grid size-9 place-items-center rounded-xl shadow-soft ring-1 ring-black/[0.03] transition-transform duration-300 group-hover:scale-105",
            t.chip,
          )}
        >
          {icon}
        </span>
      </div>

      <div className="relative mt-3 flex items-end gap-1">
        <AnimatedNumber
          value={value}
          decimals={decimals}
          className="nums text-[34px] font-extrabold leading-none tracking-tight text-ink"
        />
        {suffix && <span className="nums mb-1 text-lg font-semibold text-muted">{suffix}</span>}
      </div>

      <div className="relative mt-2.5 flex items-center gap-2">
        {typeof delta === "number" && delta !== 0 && (
          <span
            className={cn(
              "inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[11px] font-semibold",
              up ? "bg-primary-50 text-primary-700" : "bg-rose-50 text-[#be123c]",
            )}
          >
            {up ? <ArrowUpRight className="size-3" /> : <ArrowDownRight className="size-3" />}
            {Math.abs(delta)}%
          </span>
        )}
        <span className="text-[12px] text-muted">{hint}</span>
      </div>
    </motion.div>
  );
}
