import * as React from "react";
import { cn, initials } from "@/lib/utils";
import { tints } from "./tint";
import type { AccentTint, RepStatus } from "@/lib/types";

const sizeMap = {
  sm: "size-8 text-[11px]",
  md: "size-10 text-xs",
  lg: "size-12 text-sm",
  xl: "size-14 text-base",
} as const;

const presence: Record<RepStatus, string> = {
  live: "bg-primary-500",
  break: "bg-amber",
  offline: "bg-faint",
};

export function Avatar({
  name,
  tint = "emerald",
  size = "md",
  status,
  className,
}: {
  name: string;
  tint?: AccentTint;
  size?: keyof typeof sizeMap;
  status?: RepStatus;
  className?: string;
}) {
  const t = tints[tint];
  return (
    <span className={cn("relative inline-flex shrink-0", className)}>
      <span
        className={cn(
          "inline-flex items-center justify-center rounded-full font-semibold ring-1 ring-inset ring-black/[0.04]",
          sizeMap[size],
          t.chip,
        )}
      >
        {initials(name)}
      </span>
      {status && (
        <span
          className={cn(
            "absolute -bottom-0.5 -right-0.5 size-3 rounded-full border-2 border-surface",
            presence[status],
            status === "live" && "animate-[pulse-ring_2s_infinite]",
          )}
        />
      )}
    </span>
  );
}
