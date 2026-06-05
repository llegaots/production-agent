"use client";

import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

/** A number that gives a subtle pop whenever it changes — for live metrics. */
export function LiveValue({
  value,
  className,
  suffix,
}: {
  value: number | string;
  className?: string;
  suffix?: string;
}) {
  return (
    <span className={cn("nums inline-flex items-baseline", className)}>
      <motion.span
        key={String(value)}
        initial={{ scale: 1.18, color: "#059e6e" }}
        animate={{ scale: 1, color: "var(--color-ink)" }}
        transition={{ type: "spring", stiffness: 360, damping: 18 }}
        className="inline-block"
      >
        {value}
      </motion.span>
      {suffix && <span className="text-muted">{suffix}</span>}
    </span>
  );
}
