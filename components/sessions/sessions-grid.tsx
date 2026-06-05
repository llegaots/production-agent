"use client";

import { motion } from "framer-motion";
import { DoorOpen, Sparkles, Users, RadioTower } from "lucide-react";
import { SessionCard } from "./session-card";
import { EmptyState } from "@/components/ui/empty-state";
import { Button } from "@/components/ui/button";
import { staggerContainer, fadeInUp } from "@/lib/motion";
import type { Session } from "@/lib/types";

export function SessionsGrid({ sessions }: { sessions: Session[] }) {
  if (sessions.length === 0) {
    return (
      <div className="mx-auto max-w-[1400px]">
        <div className="rounded-3xl border border-line bg-surface shadow-card">
          <EmptyState
            icon={<RadioTower className="size-6" />}
            title="No reps live right now"
            description="When a marketer starts a field session, they'll appear here in real time — live transcript, AI grade, detected leads and their route drawing on the map."
            action={
              <Button size="sm" variant="secondary">
                View schedule
              </Button>
            }
          />
        </div>
      </div>
    );
  }

  const totalDoors = sessions.reduce((a, s) => a + s.doors, 0);
  const totalLeads = sessions.reduce((a, s) => a + s.leads, 0);
  const summary = [
    { label: "Reps live now", value: sessions.length, icon: Users, chip: "bg-primary-50 text-primary-700" },
    { label: "Doors this shift", value: totalDoors, icon: DoorOpen, chip: "bg-sky-50 text-[#0284c7]" },
    { label: "Leads captured", value: totalLeads, icon: Sparkles, chip: "bg-violet-50 text-[#6d28d9]" },
  ];

  return (
    <div className="mx-auto flex max-w-[1400px] flex-col gap-5">
      <motion.div
        variants={staggerContainer(0.07)}
        initial="hidden"
        animate="show"
        className="grid grid-cols-1 gap-3 sm:grid-cols-3"
      >
        {summary.map((s) => (
          <motion.div
            key={s.label}
            variants={fadeInUp}
            className="flex items-center gap-3 rounded-3xl border border-line bg-surface px-5 py-4 shadow-card"
          >
            <span className={`grid size-11 place-items-center rounded-2xl ${s.chip}`}>
              <s.icon className="size-5" />
            </span>
            <div>
              <div className="nums text-2xl font-extrabold tracking-tight text-ink">{s.value}</div>
              <div className="text-[12px] text-muted">{s.label}</div>
            </div>
          </motion.div>
        ))}
      </motion.div>

      <div>
        <h3 className="mb-3 px-1 text-sm font-semibold text-ink-soft">
          Active sessions · click any rep to watch live
        </h3>
        <motion.div
          variants={staggerContainer(0.08)}
          initial="hidden"
          animate="show"
          className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3"
        >
          {sessions.map((s) => (
            <SessionCard key={s.id} session={s} />
          ))}
        </motion.div>
      </div>
    </div>
  );
}
