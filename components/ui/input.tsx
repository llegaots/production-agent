import * as React from "react";
import { cn } from "@/lib/utils";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "h-10 w-full rounded-xl border border-line bg-surface px-3.5 text-sm text-ink placeholder:text-faint shadow-soft outline-none transition-all duration-200 focus:border-primary-200 focus:ring-2 focus:ring-primary/15",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";

export const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea
    ref={ref}
    className={cn(
      "w-full rounded-2xl border border-line bg-surface px-3.5 py-3 text-sm leading-relaxed text-ink placeholder:text-faint shadow-soft outline-none transition-all duration-200 focus:border-primary-200 focus:ring-2 focus:ring-primary/15 pretty-scroll",
      className,
    )}
    {...props}
  />
));
Textarea.displayName = "Textarea";
