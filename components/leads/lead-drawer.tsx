"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  Phone,
  Mail,
  MapPin,
  CalendarPlus,
  Bot,
  Hand,
  Quote,
  ShieldCheck,
  AlertTriangle,
  Loader2,
  Check,
  Pencil,
} from "lucide-react";
import { Drawer } from "@/components/ui/drawer";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Avatar } from "@/components/ui/avatar";
import { LeadStatusBadge } from "@/components/ui/status";
import { FieldMap } from "@/components/maps/field-map";
import { cn, timeAgo } from "@/lib/utils";
import type { Lead } from "@/lib/types";

/** Trust chip for a lead's address - drives the "needs check" review flow. */
function addressMeta(lead: Lead) {
  if (lead.addressVerified)
    return { cls: "bg-primary-50 text-primary-700", Icon: ShieldCheck, label: "Address confirmed" };
  if (lead.addressConfidence === "rooftop")
    return { cls: "bg-primary-50 text-primary-700", Icon: ShieldCheck, label: "Rooftop match" };
  if (lead.addressConfidence === "interpolated")
    return { cls: "bg-amber-50 text-[#b45309]", Icon: MapPin, label: "Approximate address" };
  return { cls: "bg-rose-50 text-[#be123c]", Icon: AlertTriangle, label: "GPS only, check address" };
}

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
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [addr, setAddr] = useState("");
  const [saving, setSaving] = useState(false);

  // Reset the inline editor whenever a different lead is shown (no effect needed).
  const [shownId, setShownId] = useState<string | null>(lead?.id ?? null);
  if ((lead?.id ?? null) !== shownId) {
    setShownId(lead?.id ?? null);
    setEditing(false);
  }

  async function saveAddress() {
    if (!lead) return;
    setSaving(true);
    try {
      const res = await fetch("/api/leads", {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ id: lead.id, address: addr }),
      });
      if (res.ok) {
        setEditing(false);
        router.refresh();
        onOpenChange(false);
      }
    } finally {
      setSaving(false);
    }
  }

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
                {(() => {
                  const { cls, Icon, label } = addressMeta(lead);
                  return (
                    <span
                      className={cn(
                        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold",
                        cls,
                      )}
                    >
                      <Icon className="size-3" /> {label}
                    </span>
                  );
                })()}
              </div>
              <p className="text-[13px] leading-relaxed text-ink-soft">{lead.summary}</p>
            </div>
          </div>

          <div className="h-[180px] overflow-hidden rounded-2xl border border-line">
            <FieldMap
              center={lead.position}
              trail={[
                { id: lead.id, at: lead.capturedAt, position: lead.position, outcome: "lead", address: lead.address },
              ]}
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
            <div className="flex items-center justify-between gap-2 border-b border-line-soft py-2.5">
              <span className="text-[12px] text-muted">Address</span>
              {editing ? (
                <span className="flex items-center gap-1.5">
                  <input
                    value={addr}
                    onChange={(e) => setAddr(e.target.value)}
                    placeholder="123 Main St, City"
                    className="h-8 w-52 rounded-lg border border-line bg-surface px-2 text-[13px] text-ink outline-none focus:border-primary-200"
                  />
                  <Button size="sm" variant="primary" disabled={saving || !addr.trim()} onClick={saveAddress}>
                    {saving ? <Loader2 className="size-3.5 animate-spin" /> : <Check className="size-3.5" />}
                  </Button>
                </span>
              ) : (
                <span className="flex items-center gap-1.5 text-[13px] font-medium text-ink">
                  <MapPin className="size-3.5 text-muted" /> {lead.address || "Unknown"}
                  <button
                    onClick={() => {
                      setAddr(lead.address ?? "");
                      setEditing(true);
                    }}
                    className="inline-flex items-center gap-0.5 text-[11px] font-semibold text-primary-600 hover:underline"
                  >
                    <Pencil className="size-3" /> Edit
                  </button>
                </span>
              )}
            </div>
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
