"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { ChevronRight, SlidersHorizontal, Map } from "lucide-react";
import { Card } from "@/components/ui/card";
import { RouteStatusBadge } from "@/components/ui/status";
import { Progress } from "@/components/ui/progress";
import { EmptyState } from "@/components/ui/empty-state";
import { fadeInUp, staggerContainer } from "@/lib/motion";
import { initials } from "@/lib/utils";
import type { TerritoryRow } from "@/lib/types";

export function TerritoryTable({ rows }: { rows: TerritoryRow[] }) {
  return (
    <Card className="overflow-hidden">
      <div className="flex items-center justify-between p-5">
        <div>
          <h3 className="text-lg font-bold tracking-tight text-ink">Territory performance</h3>
          <p className="text-[13px] text-muted">Ranked by answer rate · {rows.length} routes</p>
        </div>
        <button className="inline-flex items-center gap-1.5 rounded-xl border border-line bg-surface px-3 py-1.5 text-[13px] font-medium text-ink-soft shadow-soft transition-colors hover:bg-surface-muted">
          <SlidersHorizontal className="size-3.5" /> Filter
        </button>
      </div>

      {rows.length === 0 && (
        <EmptyState
          icon={<Map className="size-5" />}
          title="No routes yet"
          description="Create a route to start tracking territory coverage and performance."
        />
      )}

      {rows.length > 0 && (
        <div className="grid grid-cols-[1.6fr_0.7fr_1.1fr_0.6fr_0.8fr_auto] items-center gap-3 border-y border-line bg-surface-muted px-5 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-faint">
          <span>Route</span>
          <span className="text-right">Doors</span>
          <span>Answer rate</span>
          <span className="text-right">Leads</span>
          <span>Status</span>
          <span />
        </div>
      )}

      <motion.div variants={staggerContainer(0.05)} initial="hidden" animate="show">
        {[...rows]
          .sort((a, b) => b.answerRate - a.answerRate)
          .map((row) => (
            <motion.div
              key={row.id}
              variants={fadeInUp}
              className="grid grid-cols-[1.6fr_0.7fr_1.1fr_0.6fr_0.8fr_auto] items-center gap-3 border-b border-line-soft px-5 py-3.5 transition-colors last:border-0 hover:bg-surface-muted"
            >
              <div className="flex min-w-0 items-center gap-3">
                <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-primary-50 text-[11px] font-bold text-primary-700">
                  {initials(row.territory)}
                </span>
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-ink">{row.name}</div>
                  <div className="truncate text-[12px] text-muted">{row.territory}</div>
                </div>
              </div>
              <span className="nums text-right text-sm font-semibold text-ink">{row.doors}</span>
              <div className="flex items-center gap-2">
                <Progress value={row.answerRate} height="h-1.5" className="max-w-[90px]" />
                <span className="nums w-9 text-[12px] font-semibold text-ink-soft">{row.answerRate}%</span>
              </div>
              <span className="nums text-right text-sm font-semibold text-ink">{row.leads}</span>
              <RouteStatusBadge status={row.status} size="sm" />
              <Link
                href="/routes"
                className="grid size-8 place-items-center rounded-lg text-faint transition-colors hover:bg-canvas-deep hover:text-ink"
              >
                <ChevronRight className="size-4" />
              </Link>
            </motion.div>
          ))}
      </motion.div>
    </Card>
  );
}
