import { cn } from "@/lib/utils";

export function ScoreBadge({ score, className }: { score: number; className?: string }) {
  const tone =
    score >= 85
      ? "bg-primary-50 text-primary-700"
      : score >= 70
        ? "bg-sky-50 text-[#0284c7]"
        : "bg-amber-50 text-[#b45309]";
  return (
    <span
      className={cn(
        "nums inline-flex items-center justify-center rounded-lg px-2 py-1 text-[12px] font-bold tabular-nums",
        tone,
        className,
      )}
    >
      {score}
    </span>
  );
}
