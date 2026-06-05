"use client";

import { motion } from "framer-motion";
import { Sparkles, CalendarCheck, ShieldCheck, Flag, Activity } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Avatar } from "@/components/ui/avatar";
import { PulseDot } from "@/components/ui/pulse-dot";
import { EmptyState } from "@/components/ui/empty-state";
import { timeAgo } from "@/lib/utils";
import { fadeInUp, staggerContainer } from "@/lib/motion";
import type { ActivityItem } from "@/lib/types";

const kindIcon = {
  lead: Sparkles,
  appointment: CalendarCheck,
  objection: ShieldCheck,
  milestone: Flag,
} as const;

export function LiveActivity({ items }: { items: ActivityItem[] }) {
  return (
    <Card className="flex h-full flex-col p-5">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-bold tracking-tight text-ink">Live activity</h3>
        <span className="inline-flex items-center gap-1.5 text-[12px] font-medium text-muted">
          <PulseDot size="size-1.5" /> streaming
        </span>
      </div>

      {items.length === 0 && (
        <EmptyState
          compact
          className="flex-1"
          icon={<Activity className="size-5" />}
          title="Quiet for now"
          description="Lead captures, appointments and milestones stream in here live."
        />
      )}

      <motion.ul
        variants={staggerContainer(0.06)}
        initial="hidden"
        animate="show"
        className="mt-4 flex flex-1 flex-col gap-3"
      >
        {items.map((item) => {
          const Icon = kindIcon[item.kind];
          return (
            <motion.li key={item.id} variants={fadeInUp} className="flex items-start gap-3">
              <div className="relative">
                <Avatar name={item.repName} tint={item.tint} size="sm" />
                <span className="absolute -bottom-1 -right-1 grid size-4 place-items-center rounded-full bg-surface ring-1 ring-line">
                  <Icon className="size-2.5 text-primary-600" />
                </span>
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-[13px] leading-snug text-ink-soft">
                  <span className="font-semibold text-ink">{item.repName}</span> {item.text}
                </p>
                <span className="text-[11px] text-faint">{timeAgo(item.at)}</span>
              </div>
            </motion.li>
          );
        })}
      </motion.ul>
    </Card>
  );
}
