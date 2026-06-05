"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Gauge as GaugeIcon, DoorOpen, Sparkles, Users, UserPlus } from "lucide-react";
import { RepCard } from "@/components/team/rep-card";
import { EmptyState } from "@/components/ui/empty-state";
import { Button } from "@/components/ui/button";
import { AddMarketerDrawer } from "@/components/team/add-marketer-drawer";
import { RepDetailDrawer } from "@/components/team/rep-detail-drawer";
import { staggerContainer, fadeInUp } from "@/lib/motion";
import type { Rep, Route, Shift } from "@/lib/types";

export function TeamView({
  reps,
  teamId,
  routes = [],
  shifts = [],
}: {
  reps: Rep[];
  teamId: string | null;
  routes?: Route[];
  shifts?: Shift[];
}) {
  const [addOpen, setAddOpen] = useState(false);
  const [selectedRep, setSelectedRep] = useState<Rep | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const openRep = (rep: Rep) => {
    setSelectedRep(rep);
    setDetailOpen(true);
  };

  if (reps.length === 0) {
    return (
      <div className="mx-auto max-w-[1100px]">
        <div className="rounded-3xl border border-line bg-surface shadow-card">
          <EmptyState
            icon={<UserPlus className="size-6" />}
            title="No marketers yet"
            description="Invite your field reps to start tracking grades, pace and conversion. Their leaderboard builds automatically as they run sessions."
            action={
              <Button size="sm" onClick={() => setAddOpen(true)}>
                <UserPlus className="size-4" /> Add a marketer
              </Button>
            }
          />
        </div>
        <AddMarketerDrawer open={addOpen} onOpenChange={setAddOpen} teamId={teamId} />
      </div>
    );
  }

  const ranked = [...reps].sort((a, b) => b.grade - a.grade);
  const avgGrade = Math.round(ranked.reduce((a, r) => a + r.grade, 0) / ranked.length);
  const doors = ranked.reduce((a, r) => a + r.doorsToday, 0);
  const leads = ranked.reduce((a, r) => a + r.leadsToday, 0);
  const active = ranked.filter((r) => r.status === "live").length;

  const summary = [
    { label: "Team avg grade", value: avgGrade, icon: GaugeIcon, chip: "bg-primary-50 text-primary-700" },
    { label: "Doors today", value: doors, icon: DoorOpen, chip: "bg-sky-50 text-[#0284c7]" },
    { label: "Leads today", value: leads, icon: Sparkles, chip: "bg-violet-50 text-[#6d28d9]" },
    { label: "Active now", value: active, icon: Users, chip: "bg-amber-50 text-[#b45309]" },
  ];

  return (
    <div className="mx-auto flex max-w-[1400px] flex-col gap-5">
      <motion.div
        variants={staggerContainer(0.07)}
        initial="hidden"
        animate="show"
        className="grid grid-cols-2 gap-3 lg:grid-cols-4"
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
        <div className="mb-3 flex items-center justify-between px-1">
          <h3 className="text-sm font-semibold text-ink-soft">Leaderboard · ranked by grade</h3>
          <Button size="sm" onClick={() => setAddOpen(true)}>
            <UserPlus className="size-4" /> Add marketer
          </Button>
        </div>
        <motion.div
          variants={staggerContainer(0.07)}
          initial="hidden"
          animate="show"
          className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3"
        >
          {ranked.map((rep, i) => (
            <RepCard key={rep.id} rep={rep} rank={i + 1} onClick={() => openRep(rep)} />
          ))}
        </motion.div>
      </div>

      <AddMarketerDrawer open={addOpen} onOpenChange={setAddOpen} teamId={teamId} />
      <RepDetailDrawer rep={selectedRep} routes={routes} shifts={shifts} open={detailOpen} onOpenChange={setDetailOpen} />
    </div>
  );
}
