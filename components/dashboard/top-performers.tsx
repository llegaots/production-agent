"use client";

import { motion } from "framer-motion";
import { Trophy } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Avatar } from "@/components/ui/avatar";
import { Sparkline } from "@/components/ui/sparkline";
import { EmptyState } from "@/components/ui/empty-state";
import { gradeLetter } from "@/lib/utils";
import { fadeInUp, staggerContainer } from "@/lib/motion";
import type { Rep } from "@/lib/types";

export function TopPerformers({ reps }: { reps: Rep[] }) {
  const ranked = [...reps].sort((a, b) => b.grade - a.grade).slice(0, 5);

  return (
    <Card className="flex h-full flex-col p-5">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-bold tracking-tight text-ink">Top performers</h3>
          <p className="text-[13px] text-muted">Ranked by live grade</p>
        </div>
      </div>

      {ranked.length === 0 && (
        <EmptyState
          compact
          className="flex-1"
          icon={<Trophy className="size-5" />}
          title="No performers yet"
          description="Your leaderboard fills in as reps run sessions."
        />
      )}

      <motion.ul
        variants={staggerContainer(0.07)}
        initial="hidden"
        animate="show"
        className="mt-4 flex flex-1 flex-col gap-1"
      >
        {ranked.map((rep, i) => (
          <motion.li
            key={rep.id}
            variants={fadeInUp}
            className="flex items-center gap-3 rounded-2xl px-2 py-2.5 transition-colors hover:bg-surface-muted"
          >
            <span className="nums w-4 text-center text-sm font-bold text-faint">{i + 1}</span>
            <Avatar name={rep.name} tint={rep.avatarTint} size="md" status={rep.status} />
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-semibold text-ink">{rep.name}</div>
              <div className="truncate text-[12px] text-muted">{rep.territory}</div>
            </div>
            <Sparkline data={rep.trend} width={64} height={26} fill={false} />
            <div className="w-12 text-right">
              <div className="nums text-sm font-bold text-ink">{rep.grade}</div>
              <div className="text-[10px] font-semibold uppercase text-primary-600">
                {gradeLetter(rep.grade)}
              </div>
            </div>
          </motion.li>
        ))}
      </motion.ul>
    </Card>
  );
}
