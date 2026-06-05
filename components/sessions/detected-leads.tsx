"use client";

import { AnimatePresence, motion } from "framer-motion";
import { MapPin, Plus } from "lucide-react";
import { LeadStatusBadge } from "@/components/ui/status";
import { timeAgo } from "@/lib/utils";
import type { Lead } from "@/lib/types";

export function DetectedLeads({ leads }: { leads: Lead[] }) {
  return (
    <div className="flex flex-col rounded-3xl border border-line bg-surface shadow-card">
      <div className="flex items-center justify-between border-b border-line px-5 py-4">
        <div>
          <h3 className="text-base font-bold tracking-tight text-ink">Detected leads</h3>
          <p className="text-[12px] text-muted">Auto-written to CRM this session</p>
        </div>
        <span className="grid size-7 place-items-center rounded-full bg-primary-50 text-[12px] font-bold text-primary-700">
          {leads.length}
        </span>
      </div>

      <div className="space-y-2.5 p-4">
        {leads.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 py-8 text-center">
            <span className="grid size-10 place-items-center rounded-full bg-surface-muted text-faint">
              <Plus className="size-5" />
            </span>
            <p className="text-[13px] text-muted">Watching for lead signals…</p>
          </div>
        )}
        <AnimatePresence initial={false}>
          {leads.map((lead) => (
            <motion.div
              key={lead.id}
              layout
              initial={{ opacity: 0, scale: 0.9, y: -8 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ type: "spring", stiffness: 300, damping: 24 }}
              className="rounded-2xl border border-primary-100 bg-gradient-to-br from-primary-50/70 to-surface p-3.5"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-ink">{lead.name}</div>
                  <div className="mt-0.5 flex items-center gap-1 text-[12px] text-muted">
                    <MapPin className="size-3 shrink-0" />
                    <span className="truncate">{lead.address}</span>
                  </div>
                </div>
                <LeadStatusBadge status={lead.status} size="sm" />
              </div>
              <p className="mt-2 line-clamp-2 text-[12px] italic leading-snug text-ink-soft">
                “{lead.transcriptSnippet}”
              </p>
              <div className="mt-2 flex items-center justify-between">
                <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-primary-700">
                  Score {lead.score}
                </span>
                <span className="text-[11px] text-faint">{timeAgo(lead.capturedAt)}</span>
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </div>
  );
}
