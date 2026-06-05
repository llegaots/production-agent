"use client";

import { AnimatePresence, motion } from "framer-motion";
import {
  ShieldAlert,
  ListChecks,
  Timer,
  Sparkles,
  GraduationCap,
  AudioLines,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { PulseDot } from "@/components/ui/pulse-dot";
import { EmptyState } from "@/components/ui/empty-state";
import type { AgentInsight, InsightKind } from "@/lib/types";

const kindMeta: Record<InsightKind, { icon: LucideIcon; chip: string; ring: string }> = {
  objection: { icon: ShieldAlert, chip: "bg-amber-50 text-[#b45309]", ring: "#f5a623" },
  "script-adherence": { icon: ListChecks, chip: "bg-primary-50 text-primary-700", ring: "#10b981" },
  pace: { icon: Timer, chip: "bg-sky-50 text-[#0284c7]", ring: "#38bdf8" },
  "lead-detected": { icon: Sparkles, chip: "bg-violet-50 text-[#6d28d9]", ring: "#8b7cf6" },
  coaching: { icon: GraduationCap, chip: "bg-primary-50 text-primary-700", ring: "#10b981" },
  tone: { icon: AudioLines, chip: "bg-sky-50 text-[#0284c7]", ring: "#38bdf8" },
};

function ScoreRing({ score, color }: { score: number; color: string }) {
  const r = 15;
  const c = 2 * Math.PI * r;
  return (
    <div className="relative grid size-10 shrink-0 place-items-center">
      <svg width={40} height={40} className="-rotate-90">
        <circle cx={20} cy={20} r={r} fill="none" stroke="var(--color-canvas-deep)" strokeWidth={3.5} />
        <motion.circle
          cx={20}
          cy={20}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={3.5}
          strokeLinecap="round"
          strokeDasharray={c}
          initial={{ strokeDashoffset: c }}
          animate={{ strokeDashoffset: c * (1 - score / 100) }}
          transition={{ type: "spring", stiffness: 120, damping: 18 }}
        />
      </svg>
      <span className="nums absolute text-[11px] font-bold text-ink">{score}</span>
    </div>
  );
}

export function AgentPanel({ insights }: { insights: AgentInsight[] }) {
  return (
    <div className="flex h-full flex-col rounded-3xl border border-line bg-surface shadow-card">
      <div className="flex items-center justify-between border-b border-line px-5 py-4">
        <div className="flex items-center gap-2">
          <span className="grid size-8 place-items-center rounded-xl bg-gradient-to-br from-violet-50 to-primary-50 ring-1 ring-black/[0.03]">
            <Sparkles className="size-4 text-[#6d28d9]" />
          </span>
          <div>
            <h3 className="text-base font-bold tracking-tight text-ink">AI agent</h3>
            <p className="text-[12px] text-muted">Grading against your playbook</p>
          </div>
        </div>
        <span className="inline-flex items-center gap-1.5 text-[12px] font-medium text-primary-700">
          <PulseDot size="size-1.5" /> live
        </span>
      </div>

      <div className="min-h-0 flex-1 space-y-2.5 overflow-y-auto px-4 py-4 pretty-scroll">
        {insights.length === 0 && (
          <EmptyState
            compact
            className="h-full"
            icon={<Sparkles className="size-5" />}
            title="Standing by"
            description="Objection handling, tone and pace insights appear here as the conversation unfolds."
          />
        )}
        <AnimatePresence initial={false}>
          {insights.map((ins) => {
            const meta = kindMeta[ins.kind];
            const Icon = meta.icon;
            return (
              <motion.div
                key={ins.id}
                layout
                initial={{ opacity: 0, y: -10, scale: 0.97 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0 }}
                transition={{ type: "spring", stiffness: 320, damping: 28 }}
                className="flex items-start gap-3 rounded-2xl border border-line-soft bg-surface-muted/60 p-3"
              >
                <span className={cn("grid size-8 shrink-0 place-items-center rounded-lg", meta.chip)}>
                  <Icon className="size-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-[13px] font-semibold text-ink">{ins.title}</div>
                  <p className="mt-0.5 text-[12px] leading-snug text-muted">{ins.detail}</p>
                </div>
                {typeof ins.score === "number" && <ScoreRing score={ins.score} color={meta.ring} />}
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </div>
  );
}
