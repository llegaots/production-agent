"use client";

import { motion } from "framer-motion";
import { Crown } from "lucide-react";
import { Avatar } from "@/components/ui/avatar";
import { RepStatusBadge } from "@/components/ui/status";
import { Sparkline } from "@/components/ui/sparkline";
import { Gauge } from "@/components/ui/gauge";
import { cn } from "@/lib/utils";
import { fadeInUp } from "@/lib/motion";
import type { Rep } from "@/lib/types";

function Stat({ label, value, suffix }: { label: string; value: number | string; suffix?: string }) {
  return (
    <div className="rounded-xl bg-surface-muted px-3 py-2 text-center">
      <div className="nums text-base font-bold text-ink">
        {value}
        {suffix && <span className="text-[12px] text-muted">{suffix}</span>}
      </div>
      <div className="text-[10px] font-medium uppercase tracking-wide text-faint">{label}</div>
    </div>
  );
}

export function RepCard({ rep, rank, onClick }: { rep: Rep; rank: number; onClick?: () => void }) {
  const isTop = rank === 1;
  return (
    <motion.div
      variants={fadeInUp}
      whileHover={{ y: -4 }}
      transition={{ type: "spring", stiffness: 360, damping: 26 }}
      onClick={onClick}
      role="button"
      tabIndex={0}
      className={cn(
        "group relative cursor-pointer overflow-hidden rounded-3xl border bg-surface p-5 shadow-card transition-shadow hover:shadow-lift",
        isTop ? "border-primary-200 ring-1 ring-primary-100" : "border-line",
      )}
    >
      {isTop && (
        <div className="absolute right-4 top-4 inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-1 text-[11px] font-bold text-[#b45309]">
          <Crown className="size-3" /> Top rep
        </div>
      )}

      <div className="flex items-center gap-3">
        <div className="relative">
          <Avatar name={rep.name} tint={rep.avatarTint} size="lg" status={rep.status} />
          <span className="absolute -left-1.5 -top-1.5 grid size-5 place-items-center rounded-full bg-ink text-[10px] font-bold text-white">
            {rank}
          </span>
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-bold text-ink">{rep.name}</div>
          <div className="truncate text-[12px] text-muted">{rep.territory}</div>
          <div className="mt-1">
            <RepStatusBadge status={rep.status} size="sm" />
          </div>
        </div>
      </div>

      <div className="mt-4 flex items-center gap-4">
        <Gauge value={rep.grade} size={96} stroke={9} />
        <div className="flex-1">
          <div className="flex items-center justify-between text-[12px]">
            <span className="text-muted">Answer rate</span>
            <span className="nums font-semibold text-ink">{rep.answerRate}%</span>
          </div>
          <div className="mt-1 flex items-center justify-between text-[12px]">
            <span className="text-muted">Conversion</span>
            <span className="nums font-semibold text-ink">{rep.conversionRate}%</span>
          </div>
          <div className="mt-2">
            <Sparkline data={rep.trend} width={130} height={30} />
          </div>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-3 gap-2">
        <Stat label="Doors" value={rep.doorsToday} />
        <Stat label="Leads" value={rep.leadsToday} />
        <Stat label="Pace" value={rep.pace} suffix="/hr" />
      </div>
    </motion.div>
  );
}
