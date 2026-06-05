"use client";

import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

export function Progress({
  value,
  className,
  barClassName = "bg-primary-500",
  height = "h-2",
}: {
  value: number;
  className?: string;
  barClassName?: string;
  height?: string;
}) {
  return (
    <div className={cn("w-full overflow-hidden rounded-full bg-canvas-deep", height, className)}>
      <motion.div
        className={cn("h-full rounded-full", barClassName)}
        initial={{ width: 0 }}
        animate={{ width: `${Math.max(0, Math.min(100, value))}%` }}
        transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }}
      />
    </div>
  );
}
