import type { AccentTint } from "@/lib/types";

export interface TintConfig {
  /** gradient background for stat / hero cards */
  card: string;
  /** icon chip background + text */
  chip: string;
  /** soft pill background + text */
  soft: string;
  /** accent text color (high-contrast) */
  text: string;
  /** solid dot / bar background */
  solid: string;
  /** faint glow */
  glow: string;
}

export const tints: Record<AccentTint, TintConfig> = {
  emerald: {
    card: "from-primary-50 via-white to-primary-50/40",
    chip: "bg-primary-100 text-primary-700",
    soft: "bg-primary-50 text-primary-700",
    text: "text-primary-700",
    solid: "bg-primary-500",
    glow: "shadow-[0_8px_30px_-12px_rgba(16,185,129,0.5)]",
  },
  sky: {
    card: "from-sky-50 via-white to-sky-50/40",
    chip: "bg-sky-50 text-[#0284c7]",
    soft: "bg-sky-50 text-[#0284c7]",
    text: "text-[#0284c7]",
    solid: "bg-sky",
    glow: "shadow-[0_8px_30px_-12px_rgba(56,189,248,0.55)]",
  },
  violet: {
    card: "from-violet-50 via-white to-violet-50/40",
    chip: "bg-violet-50 text-[#6d28d9]",
    soft: "bg-violet-50 text-[#6d28d9]",
    text: "text-[#6d28d9]",
    solid: "bg-violet",
    glow: "shadow-[0_8px_30px_-12px_rgba(139,124,246,0.55)]",
  },
  amber: {
    card: "from-amber-50 via-white to-amber-50/40",
    chip: "bg-amber-50 text-[#b45309]",
    soft: "bg-amber-50 text-[#b45309]",
    text: "text-[#b45309]",
    solid: "bg-amber",
    glow: "shadow-[0_8px_30px_-12px_rgba(245,166,35,0.55)]",
  },
  rose: {
    card: "from-rose-50 via-white to-rose-50/40",
    chip: "bg-rose-50 text-[#be123c]",
    soft: "bg-rose-50 text-[#be123c]",
    text: "text-[#be123c]",
    solid: "bg-rose",
    glow: "shadow-[0_8px_30px_-12px_rgba(251,113,133,0.55)]",
  },
};

export const tintList: AccentTint[] = ["emerald", "sky", "violet", "amber", "rose"];
