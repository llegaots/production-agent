"use client";

import { motion } from "framer-motion";
import { ChevronRight, MapPin, Bot, Hand, Contact } from "lucide-react";
import { Avatar } from "@/components/ui/avatar";
import { LeadStatusBadge } from "@/components/ui/status";
import { EmptyState } from "@/components/ui/empty-state";
import { ScoreBadge } from "./score-badge";
import { staggerContainer, fadeInUp } from "@/lib/motion";
import { timeAgo } from "@/lib/utils";
import type { Lead } from "@/lib/types";

const cols = "grid-cols-[2.2fr_1fr_0.7fr_1.3fr_1fr_0.9fr_auto]";

export function LeadsTable({ leads, onSelect }: { leads: Lead[]; onSelect: (lead: Lead) => void }) {
  if (leads.length === 0) {
    return (
      <div className="rounded-3xl border border-line bg-surface shadow-card">
        <EmptyState
          icon={<Contact className="size-6" />}
          title="No leads yet"
          description="Leads your reps capture in the field are auto-detected, transcribed and graded - they'll land here in real time."
        />
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-3xl border border-line bg-surface shadow-card">
      <div className="overflow-x-auto pretty-scroll">
        <div className="min-w-[860px]">
          <div
            className={`grid ${cols} items-center gap-3 border-b border-line bg-surface-muted px-5 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-faint`}
          >
            <span>Lead</span>
            <span>Status</span>
            <span>Score</span>
            <span>Rep</span>
            <span>Captured</span>
            <span>Source</span>
            <span />
          </div>

          <motion.div variants={staggerContainer(0.04)} initial="hidden" animate="show">
            {leads.map((lead) => (
              <motion.button
                key={lead.id}
                variants={fadeInUp}
                onClick={() => onSelect(lead)}
                className={`grid w-full ${cols} items-center gap-3 border-b border-line-soft px-5 py-3.5 text-left transition-colors last:border-0 hover:bg-surface-muted`}
              >
                <div className="flex min-w-0 items-center gap-3">
                  <Avatar name={lead.name} tint="emerald" size="md" />
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold text-ink">{lead.name}</div>
                    <div className="flex items-center gap-1 truncate text-[12px] text-muted">
                      <MapPin className="size-3 shrink-0" />
                      <span className="truncate">{lead.address}</span>
                    </div>
                  </div>
                </div>
                <LeadStatusBadge status={lead.status} size="sm" />
                <ScoreBadge score={lead.score} />
                <div className="flex min-w-0 items-center gap-2">
                  <Avatar name={lead.repName} tint="sky" size="sm" />
                  <span className="truncate text-[13px] text-ink-soft">{lead.repName}</span>
                </div>
                <span className="text-[12px] text-muted">{timeAgo(lead.capturedAt)}</span>
                <span className="inline-flex items-center gap-1.5 text-[12px] text-muted">
                  {lead.source === "auto-detected" ? (
                    <Bot className="size-3.5 text-primary-600" />
                  ) : (
                    <Hand className="size-3.5 text-faint" />
                  )}
                  {lead.source === "auto-detected" ? "AI" : "Manual"}
                </span>
                <ChevronRight className="size-4 text-faint" />
              </motion.button>
            ))}
          </motion.div>
        </div>
      </div>
    </div>
  );
}
