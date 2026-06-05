"use client";

import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { LiveValue } from "@/components/ui/live-value";
import { fadeInUp } from "@/lib/motion";

export function MetricStat({
  label,
  value,
  suffix,
  icon,
  chip = "bg-primary-50 text-primary-700",
}: {
  label: string;
  value: number | string;
  suffix?: string;
  icon: React.ReactNode;
  chip?: string;
}) {
  return (
    <motion.div
      variants={fadeInUp}
      className="flex items-center gap-3 rounded-2xl border border-line bg-surface px-4 py-3 shadow-soft"
    >
      <span className={cn("grid size-9 shrink-0 place-items-center rounded-xl", chip)}>{icon}</span>
      <div className="min-w-0">
        <div className="text-[11px] font-medium uppercase tracking-wide text-faint">{label}</div>
        <LiveValue value={value} suffix={suffix} className="text-lg font-bold text-ink" />
      </div>
    </motion.div>
  );
}
