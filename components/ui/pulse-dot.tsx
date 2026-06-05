import { cn } from "@/lib/utils";

export function PulseDot({
  className,
  color = "bg-primary-500",
  size = "size-2",
}: {
  className?: string;
  color?: string;
  size?: string;
}) {
  return (
    <span className={cn("relative inline-flex", size, className)}>
      <span className={cn("absolute inline-flex h-full w-full animate-ping rounded-full opacity-60", color)} />
      <span className={cn("relative inline-flex rounded-full", size, color)} />
    </span>
  );
}

export function LiveBadge({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full bg-primary-50 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-primary-700",
        className,
      )}
    >
      <PulseDot size="size-1.5" />
      Live
    </span>
  );
}
