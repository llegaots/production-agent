"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { cn, formatNumber } from "@/lib/utils";

export interface BarDatum {
  label: string;
  value: number;
}

export function BarChart({
  data,
  height = 220,
  highlightLast = true,
}: {
  data: BarDatum[];
  height?: number;
  highlightLast?: boolean;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(...data.map((d) => d.value), 1);
  const niceMax = Math.ceil(max / 100) * 100;
  const ticks = 4;

  return (
    <div className="select-none">
      <div className="relative flex" style={{ height }}>
        {/* gridlines + y labels */}
        <div className="absolute inset-0 flex flex-col justify-between">
          {Array.from({ length: ticks + 1 }).map((_, i) => {
            const v = Math.round((niceMax / ticks) * (ticks - i));
            return (
              <div key={i} className="flex items-center gap-2">
                <span className="nums w-8 shrink-0 text-right text-[10px] text-faint">
                  {formatNumber(v, true)}
                </span>
                <span className="h-px flex-1 bg-line-soft" />
              </div>
            );
          })}
        </div>

        {/* bars */}
        <div className="relative ml-10 flex flex-1 items-end justify-between gap-2 pb-0">
          {data.map((d, i) => {
            const isLast = highlightLast && i === data.length - 1;
            const active = hover === i;
            const h = (d.value / niceMax) * height;
            return (
              <div
                key={d.label}
                className="group relative flex h-full flex-1 items-end justify-center"
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)}
              >
                {active && (
                  <div className="absolute -top-1 left-1/2 z-10 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-lg bg-ink px-2 py-1 text-[11px] font-semibold text-white shadow-lift">
                    {formatNumber(d.value)} doors
                  </div>
                )}
                <motion.div
                  initial={{ height: 0 }}
                  whileInView={{ height: Math.max(h, 6) }}
                  viewport={{ once: true, margin: "-10%" }}
                  transition={{ duration: 0.8, delay: i * 0.06, ease: [0.22, 1, 0.36, 1] }}
                  className={cn(
                    "w-full max-w-[44px] rounded-t-lg transition-colors duration-200",
                    isLast
                      ? "bg-gradient-to-t from-primary-500 to-primary-400"
                      : active
                        ? "bg-primary-200"
                        : "bg-primary-100",
                  )}
                />
              </div>
            );
          })}
        </div>
      </div>

      {/* x labels */}
      <div className="ml-10 mt-2 flex justify-between gap-2">
        {data.map((d, i) => (
          <span
            key={d.label}
            className={cn(
              "flex-1 text-center text-[11px]",
              highlightLast && i === data.length - 1 ? "font-semibold text-ink" : "text-muted",
            )}
          >
            {d.label}
          </span>
        ))}
      </div>
    </div>
  );
}
