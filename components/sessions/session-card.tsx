"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { DoorOpen, MessagesSquare, Sparkles, ArrowRight } from "lucide-react";
import { Avatar } from "@/components/ui/avatar";
import { LiveBadge } from "@/components/ui/pulse-dot";
import { VectorMap } from "@/components/maps/vector-map";
import { gradeLetter } from "@/lib/utils";
import { fadeInUp } from "@/lib/motion";
import type { LatLng, Session } from "@/lib/types";

export function SessionCard({ session, path }: { session: Session; path?: LatLng[] }) {
  return (
    <motion.div
      variants={fadeInUp}
      whileHover={{ y: -4 }}
      transition={{ type: "spring", stiffness: 360, damping: 26 }}
      className="group overflow-hidden rounded-3xl border border-line bg-surface shadow-card"
    >
      <Link href={`/sessions/${session.id}`} className="block">
        <div className="relative h-[150px]">
          <VectorMap path={path} trail={session.trail} live={session.position} progress={0.62} className="h-full" />
          <div className="absolute left-3 top-3">
            <LiveBadge />
          </div>
          <div className="absolute right-3 top-3 grid size-11 place-items-center rounded-2xl bg-surface/90 shadow-soft backdrop-blur">
            <div className="text-center leading-none">
              <div className="nums text-sm font-extrabold text-ink">{session.grade}</div>
              <div className="text-[8px] font-bold uppercase text-primary-600">
                {gradeLetter(session.grade)}
              </div>
            </div>
          </div>
        </div>

        <div className="p-4">
          <div className="flex items-center gap-3">
            <Avatar name={session.repName} tint="emerald" size="md" status="live" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-bold text-ink">{session.repName}</div>
              <div className="truncate text-[12px] text-muted">{session.territory}</div>
            </div>
            <ArrowRight className="size-4 text-faint transition-transform group-hover:translate-x-1 group-hover:text-primary-600" />
          </div>

          <div className="mt-4 grid grid-cols-3 gap-2">
            <Metric icon={<DoorOpen className="size-3.5" />} label="Doors" value={session.doors} />
            <Metric icon={<MessagesSquare className="size-3.5" />} label="Convos" value={session.conversations} />
            <Metric icon={<Sparkles className="size-3.5" />} label="Leads" value={session.leads} />
          </div>
        </div>
      </Link>
    </motion.div>
  );
}

function Metric({ icon, label, value }: { icon: React.ReactNode; label: string; value: number }) {
  return (
    <div className="rounded-2xl bg-surface-muted px-3 py-2.5">
      <div className="flex items-center gap-1 text-[10px] font-medium uppercase tracking-wide text-faint">
        <span className="text-primary-600">{icon}</span>
        {label}
      </div>
      <div className="nums mt-0.5 text-base font-bold text-ink">{value}</div>
    </div>
  );
}
