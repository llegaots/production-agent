import { cn } from "@/lib/utils";

export function Logo({ className }: { className?: string }) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <div className="relative grid size-9 place-items-center rounded-2xl bg-gradient-to-br from-primary-400 to-primary-700 shadow-[0_6px_16px_-6px_rgba(16,185,129,0.7)]">
        <svg viewBox="0 0 24 24" fill="none" className="size-6 text-white">
          {/* Two separate L-routes wiring the nodes (circuit style). Laid out with
              2-fold point symmetry and an empty center, so it never forms a 4-armed
              (swastika) shape. */}
          <path
            d="M12 5.7V9H8v3H5.7"
            stroke="currentColor"
            strokeWidth="1.9"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d="M18.3 12H16v3h-4v3.3"
            stroke="currentColor"
            strokeWidth="1.9"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          {/* node rings (top, left, right, bottom) */}
          <circle cx="12" cy="3.6" r="2.1" stroke="currentColor" strokeWidth="1.9" />
          <circle cx="3.6" cy="12" r="2.1" stroke="currentColor" strokeWidth="1.9" />
          <circle cx="20.4" cy="12" r="2.1" stroke="currentColor" strokeWidth="1.9" />
          <circle cx="12" cy="20.4" r="2.1" stroke="currentColor" strokeWidth="1.9" />
        </svg>
      </div>
      <div className="leading-none">
        <div className="font-display text-[17px] font-extrabold tracking-tight text-ink">
          Canvas<span className="text-primary-600">IQ</span>
        </div>
      </div>
    </div>
  );
}
