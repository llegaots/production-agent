"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Plus, Loader2, Check } from "lucide-react";
import { Drawer } from "@/components/ui/drawer";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Avatar } from "@/components/ui/avatar";
import { LeadStatusBadge } from "@/components/ui/status";
import { Field } from "@/components/ui/field";
import { cn } from "@/lib/utils";
import type { LeadStatus, Rep } from "@/lib/types";

const STATUSES: LeadStatus[] = ["new", "qualified", "callback", "appointment", "won", "lost"];

export function AddLeadDrawer({
  open,
  onOpenChange,
  reps,
  teamId,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  reps: Rep[];
  teamId: string | null;
}) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [address, setAddress] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<LeadStatus>("new");
  const [score, setScore] = useState(60);
  const [marketerId, setMarketerId] = useState<string | null>(null);
  const [summary, setSummary] = useState("");
  const [tags, setTags] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    if (!name.trim()) return;
    setBusy(true);
    setError("");
    const rep = reps.find((r) => r.id === marketerId);
    try {
      const res = await fetch("/api/leads", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          name,
          address,
          phone,
          email,
          status,
          score,
          marketer_id: marketerId,
          territory: rep?.territory,
          summary,
          tags: tags.split(",").map((t) => t.trim()).filter(Boolean),
          team_id: teamId,
          source: "manual",
        }),
      });
      const json = await res.json();
      if (!res.ok) {
        setError(json.error ?? "Could not add lead");
        return;
      }
      setName("");
      setAddress("");
      setPhone("");
      setEmail("");
      setSummary("");
      setTags("");
      setMarketerId(null);
      onOpenChange(false);
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Network error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Drawer open={open} onOpenChange={onOpenChange} title="Add a lead" description="Log a prospect into the CRM" widthClass="max-w-lg">
      <div className="flex flex-col gap-5 p-6">
        <Field label="Name">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Eleanor Whitman" autoFocus />
        </Field>
        <Field label="Address">
          <Input value={address} onChange={(e) => setAddress(e.target.value)} placeholder="214 Carlaw Ave, Leslieville" />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Phone">
            <Input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="(416) 555-0142" />
          </Field>
          <Field label="Email">
            <Input value={email} onChange={(e) => setEmail(e.target.value)} type="email" placeholder="optional" />
          </Field>
        </div>

        <div>
          <span className="mb-2 block text-[12px] font-medium text-ink-soft">Status</span>
          <div className="flex flex-wrap gap-1.5">
            {STATUSES.map((s) => (
              <button key={s} onClick={() => setStatus(s)} className={cn("rounded-full transition-all", status === s ? "ring-2 ring-ink/15" : "opacity-60 hover:opacity-100")}>
                <LeadStatusBadge status={s} size="sm" />
              </button>
            ))}
          </div>
        </div>

        <Field label={`Lead score - ${score}`}>
          <input type="range" min={0} max={100} value={score} onChange={(e) => setScore(Number(e.target.value))} className="w-full accent-primary-500" />
        </Field>

        <div>
          <span className="mb-2 block text-[12px] font-medium text-ink-soft">Captured by</span>
          {reps.length === 0 ? (
            <p className="rounded-2xl border border-dashed border-line bg-surface-muted/60 px-3 py-3 text-[12px] text-muted">
              No marketers yet - add one in Team first to attribute the lead.
            </p>
          ) : (
            <div className="flex flex-col gap-1.5">
              {reps.map((rep) => {
                const active = marketerId === rep.id;
                return (
                  <button
                    key={rep.id}
                    onClick={() => setMarketerId(active ? null : rep.id)}
                    className={cn(
                      "flex items-center gap-3 rounded-2xl border px-3 py-2 text-left transition-colors",
                      active ? "border-primary-200 bg-primary-50" : "border-line hover:bg-surface-muted",
                    )}
                  >
                    <Avatar name={rep.name} tint={rep.avatarTint} size="sm" />
                    <span className="min-w-0 flex-1 truncate text-[13px] font-semibold text-ink">{rep.name}</span>
                    {active && <Check className="size-4 text-primary-600" />}
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <Field label="Summary">
          <Textarea value={summary} onChange={(e) => setSummary(e.target.value)} rows={3} placeholder="What did they say? Intent, timeline, objections…" />
        </Field>
        <Field label="Tags (comma-separated)">
          <Input value={tags} onChange={(e) => setTags(e.target.value)} placeholder="roof, hot, homeowner" />
        </Field>

        {error && <p className="rounded-xl bg-rose-50 px-3 py-2 text-[12px] text-[#be123c]">{error}</p>}

        <div className="flex gap-2 pt-1">
          <Button className="flex-1" onClick={submit} disabled={busy || !name.trim()}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : <Plus className="size-4" />}
            Add lead
          </Button>
          <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
        </div>
      </div>
    </Drawer>
  );
}
