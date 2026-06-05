"use client";

import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

/** Live audio waveform driven by a 0–1 level. */
export function MicWave({ level, bars = 18, className }: { level: number; bars?: number; className?: string }) {
  return (
    <div className={cn("flex items-center gap-[3px]", className)}>
      {Array.from({ length: bars }).map((_, i) => {
        const phase = Math.sin((i / bars) * Math.PI);
        const h = 3 + level * 22 * (0.4 + phase * 0.8) * (0.6 + Math.random() * 0.6);
        return (
          <motion.span
            key={i}
            className="w-[3px] rounded-full bg-primary-500"
            animate={{ height: Math.max(3, h) }}
            transition={{ duration: 0.12, ease: "easeOut" }}
          />
        );
      })}
    </div>
  );
}
