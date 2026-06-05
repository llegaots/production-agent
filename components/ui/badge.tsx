import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badge = cva(
  "inline-flex items-center gap-1.5 rounded-full font-medium whitespace-nowrap transition-colors",
  {
    variants: {
      variant: {
        emerald: "bg-primary-50 text-primary-700",
        sky: "bg-sky-50 text-[#0284c7]",
        violet: "bg-violet-50 text-[#6d28d9]",
        amber: "bg-amber-50 text-[#b45309]",
        rose: "bg-rose-50 text-[#be123c]",
        neutral: "bg-canvas-deep text-ink-soft",
        outline: "border border-line text-ink-soft",
        success: "bg-primary-50 text-primary-700",
        warning: "bg-amber-50 text-[#b45309]",
        danger: "bg-rose-50 text-[#be123c]",
      },
      size: {
        sm: "px-2 py-0.5 text-[11px]",
        md: "px-2.5 py-1 text-xs",
      },
    },
    defaultVariants: { variant: "neutral", size: "md" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badge> {
  dot?: boolean;
}

export function Badge({ className, variant, size, dot, children, ...props }: BadgeProps) {
  return (
    <span className={cn(badge({ variant, size }), className)} {...props}>
      {dot && <span className="size-1.5 rounded-full bg-current opacity-80" />}
      {children}
    </span>
  );
}
