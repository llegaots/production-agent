"use client";

import { motion } from "framer-motion";
import { DoorOpen, MessagesSquare, Sparkles, Radio } from "lucide-react";
import { StatCard } from "@/components/ui/stat-card";
import { staggerContainer } from "@/lib/motion";
import type { KpiStat } from "@/lib/types";

const icons: Record<string, React.ReactNode> = {
  DoorOpen: <DoorOpen className="size-[18px]" />,
  MessagesSquare: <MessagesSquare className="size-[18px]" />,
  Sparkles: <Sparkles className="size-[18px]" />,
  Radio: <Radio className="size-[18px]" />,
};

export function KpiRow({ kpis }: { kpis: KpiStat[] }) {
  return (
    <motion.div
      variants={staggerContainer(0.08)}
      initial="hidden"
      animate="show"
      className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4"
    >
      {kpis.map((k) => (
        <StatCard
          key={k.id}
          label={k.label}
          value={k.value}
          suffix={k.suffix}
          hint={k.hint}
          delta={k.delta}
          tint={k.tint}
          icon={icons[k.icon]}
        />
      ))}
    </motion.div>
  );
}
