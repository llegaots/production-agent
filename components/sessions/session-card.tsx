"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { DoorOpen, MessagesSquare, Sparkles, ArrowRight } from "lucide-react";
import { Avatar } from "@/components/ui/avatar";
import { LiveBadge } from "@/components/ui/pulse-dot";
import { FieldMap } from "@/components/maps/field-map";
import { gradeLetter, cn } from "@/lib/utils";
import { fadeInUp } from "@/lib/motion";
import type { LatLng, Session, TranscriptLine } from "@/lib/types";

const speakerStyle: Record<string, { label: string; cls: string }> = {
  rep: { label: "Rep", cls: "text-primary-700" },
  prospect: { label: "Prospect", cls: "text-ink" },
  agent: { label: "AI", cls: "text-muted" },
};

export function SessionCard({
  session,
  path,
  latestLines = [],
}: {
  session: Session;
  path?: LatLng[];
  latestLines?: TranscriptLine[];
}) {
  // last couple of spoken lines (skip the "walking" agent notes)
  const convo = latestLines.filter((l) => l.speaker !== "agent").slice(-2);

  return (
    <motion.div
      variants={fadeInUp}
      whileHover={{ y: -4 }}
      transition={{ type: "spring", stiffness: 360, damping: 26 }}
      className="group overflow-hidden rounded-3xl border border-line bg-surface shadow-card"
    >
      <Link href={`/sessions/${session.id}`} className="block">
        <div className="relative h-[150px]">
          <FieldMap
            center={session.position}
            path={path ?? session.routePath}
            mutePath
            breadcrumb={session.trailPath}
            trail={session.trail}
            live={session.position}
            interactive={false}
            className="h-full"
          />
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

          {/* live conversation peek — fixed height so the card never resizes */}
          <div className="mt-3 flex h-[52px] flex-col justify-center gap-1 overflow-hidden rounded-2xl border border-line-soft bg-surface-muted/50 px-3 py-2">
            {convo.length ? (
              convo.map((l) => {
                const s = speakerStyle[l.speaker] ?? speakerStyle.prospect;
                return (
                  <p key={l.id} className="truncate text-[11.5px] leading-snug">
                    <span className={cn("font-semibold", s.cls)}>{s.label}:</span>{" "}
                    <span className="text-ink-soft">{l.text}</span>
                  </p>
                );
              })
            ) : (
              <p className="flex items-center gap-1.5 text-[11.5px] text-faint">
                <MessagesSquare className="size-3.5" /> Listening for conversation...
              </p>
            )}
          </div>

          <div className="mt-3 grid grid-cols-3 gap-2">
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
