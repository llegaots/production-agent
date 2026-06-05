"use client";

import { motion } from "framer-motion";
import { MapPin } from "lucide-react";
import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { ScoreBadge } from "./score-badge";
import { fadeInUp, staggerContainer } from "@/lib/motion";
import type { Lead, LeadStatus } from "@/lib/types";

const columns: { status: LeadStatus; label: string; accent: string }[] = [
  { status: "new", label: "New", accent: "bg-sky" },
  { status: "qualified", label: "Qualified", accent: "bg-violet" },
  { status: "callback", label: "Callback", accent: "bg-amber" },
  { status: "appointment", label: "Appointment", accent: "bg-primary-500" },
  { status: "won", label: "Won", accent: "bg-primary-600" },
  { status: "lost", label: "Lost", accent: "bg-faint" },
];

export function LeadsKanban({ leads, onSelect }: { leads: Lead[]; onSelect: (lead: Lead) => void }) {
  return (
    <div className="overflow-x-auto pb-2 pretty-scroll">
      <div className="flex min-w-max gap-4">
        {columns.map((col) => {
          const items = leads.filter((l) => l.status === col.status);
          return (
            <div key={col.status} className="flex w-[280px] shrink-0 flex-col">
              <div className="mb-3 flex items-center gap-2 px-1">
                <span className={`size-2 rounded-full ${col.accent}`} />
                <span className="text-[13px] font-semibold text-ink">{col.label}</span>
                <span className="nums rounded-full bg-canvas-deep px-1.5 text-[11px] font-bold text-muted">
                  {items.length}
                </span>
              </div>

              <motion.div
                variants={staggerContainer(0.05)}
                initial="hidden"
                animate="show"
                className="flex flex-col gap-2.5 rounded-3xl bg-surface-muted/60 p-2.5"
              >
                {items.length === 0 && (
                  <div className="rounded-2xl border border-dashed border-line py-8 text-center text-[12px] text-faint">
                    No leads
                  </div>
                )}
                {items.map((lead) => (
                  <motion.button
                    layout
                    key={lead.id}
                    variants={fadeInUp}
                    onClick={() => onSelect(lead)}
                    whileHover={{ y: -3 }}
                    transition={{ type: "spring", stiffness: 380, damping: 26 }}
                    className="w-full rounded-2xl border border-line bg-surface p-3.5 text-left shadow-soft"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-semibold text-ink">{lead.name}</div>
                        <div className="mt-0.5 flex items-center gap-1 text-[12px] text-muted">
                          <MapPin className="size-3 shrink-0" />
                          <span className="truncate">{lead.address}</span>
                        </div>
                      </div>
                      <ScoreBadge score={lead.score} />
                    </div>
                    <div className="mt-3 flex flex-wrap gap-1">
                      {lead.tags.slice(0, 2).map((t) => (
                        <Badge key={t} variant="neutral" size="sm">
                          {t}
                        </Badge>
                      ))}
                    </div>
                    <div className="mt-3 flex items-center gap-2 border-t border-line-soft pt-2.5">
                      <Avatar name={lead.repName} tint="sky" size="sm" />
                      <span className="truncate text-[12px] text-muted">{lead.repName}</span>
                    </div>
                  </motion.button>
                ))}
              </motion.div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
