"use client";

import { Phone, Mail, MapPin, CalendarPlus, Bot, Hand, Quote } from "lucide-react";
import { Drawer } from "@/components/ui/drawer";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Avatar } from "@/components/ui/avatar";
import { LeadStatusBadge } from "@/components/ui/status";
import { VectorMap } from "@/components/maps/vector-map";
import { gradeLetter, timeAgo } from "@/lib/utils";
import type { Lead } from "@/lib/types";

function ScoreDial({ score }: { score: number }) {
  const r = 26;
  const c = 2 * Math.PI * r;
  const color = score >= 85 ? "#10b981" : score >= 70 ? "#38bdf8" : "#f5a623";
  return (
    <div className="relative grid size-16 shrink-0 place-items-center">
      <svg width={64} height={64} className="-rotate-90">
        <circle cx={32} cy={32} r={r} fill="none" stroke="var(--color-canvas-deep)" strokeWidth={5} />
        <circle
          cx={32}
          cy={32}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={5}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - score / 100)}
        />
      </svg>
      <div className="absolute text-center leading-none">
        <div className="nums text-base font-extrabold text-ink">{score}</div>
        <div className="text-[8px] font-bold uppercase text-muted">score</div>
      </div>
    </div>
  );
}

function MetaRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between border-b border-line-soft py-2.5 last:border-0">
      <span className="text-[12px] text-muted">{label}</span>
      <span className="text-[13px] font-medium text-ink">{value}</span>
    </div>
  );
}

export function LeadDrawer({
  lead,
  open,
  onOpenChange,
}: {
  lead: Lead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Drawer
      open={open}
      onOpenChange={onOpenChange}
      title={lead?.name}
      description={lead ? lead.address : undefined}
      widthClass="max-w-lg"
    >
      {lead && (
        <div className="flex flex-col gap-5 p-6">
          <div className="flex items-start gap-4 rounded-2xl border border-primary-100 bg-gradient-to-br from-primary-50/60 to-surface p-4">
            <ScoreDial score={lead.score} />
            <div className="min-w-0 flex-1">
              <div className="mb-1.5 flex items-center gap-2">
                <LeadStatusBadge status={lead.status} size="sm" />
                <span className="inline-flex items-center gap-1 text-[11px] text-muted">
                  {lead.source === "auto-detected" ? (
                    <>
                      <Bot className="size-3 text-primary-600" /> AI-detected
                    </>
                  ) : (
                    <>
                      <Hand className="size-3" /> Manual
                    </>
                  )}
                </span>
              </div>
              <p className="text-[13px] leading-relaxed text-ink-soft">{lead.summary}</p>
            </div>
          </div>

          <div className="h-[180px] overflow-hidden rounded-2xl border border-line">
            <VectorMap
              live={lead.position}
              trail={[
                { id: lead.id, at: lead.capturedAt, position: lead.position, outcome: "lead" },
              ]}
              progress={0}
              className="h-full"
            />
          </div>

          <div className="rounded-2xl border border-line bg-surface-muted/50 p-4">
            <div className="flex items-start gap-2 text-[13px] italic leading-relaxed text-ink-soft">
              <Quote className="mt-0.5 size-4 shrink-0 text-primary-400" />
              <p>{lead.transcriptSnippet}</p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <Button variant="primary" size="sm" className="w-full">
              <CalendarPlus className="size-4" /> Book appointment
            </Button>
            {lead.phone ? (
              <Button variant="secondary" size="sm" className="w-full">
                <Phone className="size-4" /> Call
              </Button>
            ) : (
              <Button variant="secondary" size="sm" className="w-full">
                <Mail className="size-4" /> Email
              </Button>
            )}
          </div>

          <div className="rounded-2xl border border-line p-4">
            {lead.phone && <MetaRow label="Phone" value={lead.phone} />}
            {lead.email && <MetaRow label="Email" value={lead.email} />}
            <MetaRow
              label="Address"
              value={
                <span className="inline-flex items-center gap-1">
                  <MapPin className="size-3.5 text-muted" /> {lead.address}
                </span>
              }
            />
            <MetaRow
              label="Captured by"
              value={
                <span className="inline-flex items-center gap-1.5">
                  <Avatar name={lead.repName} tint="sky" size="sm" /> {lead.repName}
                </span>
              }
            />
            <MetaRow label="Territory" value={lead.territory} />
            <MetaRow label="Captured" value={timeAgo(lead.capturedAt)} />
          </div>

          <div className="flex flex-wrap gap-1.5">
            {lead.tags.map((t) => (
              <Badge key={t} variant="emerald" size="md">
                {t}
              </Badge>
            ))}
          </div>
        </div>
      )}
    </Drawer>
  );
}
