import { cn } from "@/lib/utils";

export function Logo({ className }: { className?: string }) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <div className="relative grid size-9 place-items-center rounded-2xl bg-gradient-to-br from-primary-400 to-primary-700 shadow-[0_6px_16px_-6px_rgba(16,185,129,0.7)]">
        <svg viewBox="0 0 24 24" fill="none" className="size-5 text-white">
          <path
            d="M12 2.5c-3.6 0-6.5 2.8-6.5 6.4 0 4.5 6.5 12.6 6.5 12.6s6.5-8.1 6.5-12.6c0-3.6-2.9-6.4-6.5-6.4Z"
            fill="currentColor"
            opacity="0.25"
          />
          <circle cx="12" cy="9" r="2.6" fill="currentColor" />
          <path
            d="M7.2 13.8a6.8 6.8 0 0 0 9.6 0"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            opacity="0.85"
          />
        </svg>
      </div>
      <div className="leading-none">
        <div className="font-display text-[17px] font-extrabold tracking-tight text-ink">
          Route<span className="text-primary-600">IQ</span>
        </div>
      </div>
    </div>
  );
}
