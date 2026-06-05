"use client";

import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
  compact = false,
}: {
  icon: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
  compact?: boolean;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
      className={cn(
        "flex flex-col items-center justify-center text-center",
        compact ? "gap-2 py-10" : "gap-3 py-16",
        className,
      )}
    >
      <div className="relative">
        <div className="absolute inset-0 rounded-2xl bg-primary-100/50 blur-xl" />
        <span
          className={cn(
            "relative grid place-items-center rounded-2xl bg-primary-50 text-primary-600 ring-1 ring-primary-100",
            compact ? "size-11" : "size-14",
          )}
        >
          {icon}
        </span>
      </div>
      <div>
        <h4 className={cn("font-semibold text-ink", compact ? "text-sm" : "text-base")}>{title}</h4>
        {description && (
          <p className="mx-auto mt-1 max-w-sm text-[13px] leading-relaxed text-muted">{description}</p>
        )}
      </div>
      {action && <div className="mt-1">{action}</div>}
    </motion.div>
  );
}
