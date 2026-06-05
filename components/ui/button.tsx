"use client";

import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const button = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl font-medium transition-all duration-200 outline-none focus-visible:ring-2 focus-visible:ring-primary/40 disabled:opacity-50 disabled:pointer-events-none active:scale-[0.97] select-none",
  {
    variants: {
      variant: {
        primary:
          "bg-primary text-primary-fg shadow-[0_1px_2px_rgba(5,158,110,0.4),0_8px_20px_-8px_rgba(16,185,129,0.6)] hover:bg-primary-600 hover:shadow-[0_1px_2px_rgba(5,158,110,0.4),0_10px_26px_-8px_rgba(16,185,129,0.7)]",
        secondary:
          "bg-surface text-ink border border-line shadow-soft hover:bg-surface-muted hover:border-line",
        subtle: "bg-primary-50 text-primary-700 hover:bg-primary-100",
        ghost: "text-ink-soft hover:bg-canvas-deep hover:text-ink",
        outline: "border border-line text-ink-soft hover:bg-surface-muted hover:text-ink",
        danger: "bg-rose-50 text-[#be123c] hover:bg-rose-50/70",
      },
      size: {
        sm: "h-8 px-3 text-[13px]",
        md: "h-10 px-4 text-sm",
        lg: "h-11 px-5 text-sm",
        icon: "h-9 w-9 p-0",
        "icon-sm": "h-8 w-8 p-0",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof button> {
  asChild?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp ref={ref} className={cn(button({ variant, size }), className)} {...props} />
    );
  },
);
Button.displayName = "Button";
