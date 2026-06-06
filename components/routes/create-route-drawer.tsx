"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { MapPinned, Check, Loader2 } from "lucide-react";
import { Drawer } from "@/components/ui/drawer";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Avatar } from "@/components/ui/avatar";
import { cn } from "@/lib/utils";
import { Field } from "@/components/ui/field";
import type { Rep } from "@/lib/types";

export function CreateRouteDrawer({
  open,
  onOpenChange,
  reps,
  teamId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  reps: Rep[];
  teamId: string | null;
}) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [territory, setTerritory] = useState("");
  const [doors, setDoors] = useState(120);
  const [scheduledFor, setScheduledFor] = useState("");
  const [assigned, setAssigned] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const toggle = (id: string) =>
    setAssigned((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id].slice(0, 3)));

  async function submit() {
    if (!name.trim()) return;
    setBusy(true);
    setError("");
    try {
      const res = await fetch("/api/routes", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          name,
          territory,
          doorsPlanned: doors,
          scheduledFor: scheduledFor || null,
          marketerIds: assigned,
          teamId,
        }),
      });
      const json = await res.json();
      if (!res.ok) {
        setError(json.error ?? "Could not create route");
        return;
      }
      setName("");
      setTerritory("");
      setAssigned([]);
      onOpenChange(false);
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Network error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Drawer
      open={open}
      onOpenChange={onOpenChange}
      title="Create route"
      description="Add a route by hand (or use Generate with AI for street-mapped routes)"
      widthClass="max-w-md"
    >
      <div className="flex flex-col gap-5 p-6">
        <div className="grid h-28 place-items-center rounded-2xl border border-dashed border-line bg-surface-muted/60 text-center">
          <div>
            <span className="mx-auto grid size-9 place-items-center rounded-full bg-primary-50 text-primary-700">
              <MapPinned className="size-4.5" />
            </span>
            <p className="mt-1.5 text-[12px] text-muted">Manual route - no drawn path yet</p>
            <p className="text-[11px] text-faint">AI generation maps it to real streets</p>
          </div>
        </div>

        <Field label="Route name">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Leslieville - Queen E Grid" autoFocus />
        </Field>
        <Field label="Territory">
          <Input value={territory} onChange={(e) => setTerritory(e.target.value)} placeholder="e.g. Leslieville" />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Target doors">
            <Input type="number" value={doors} onChange={(e) => setDoors(Number(e.target.value))} />
          </Field>
          <Field label="Scheduled for">
            <Input type="date" value={scheduledFor} onChange={(e) => setScheduledFor(e.target.value)} />
          </Field>
        </div>

        <div>
          <span className="mb-2 block text-[12px] font-medium text-ink-soft">Assign marketers (a pair)</span>
          {reps.length === 0 && (
            <p className="rounded-2xl border border-dashed border-line bg-surface-muted/60 px-3 py-3 text-[12px] text-muted">
              No reps on the team yet - add marketers in Team first.
            </p>
          )}
          <div className="flex flex-col gap-1.5">
            {reps.map((rep) => {
              const active = assigned.includes(rep.id);
              return (
                <button
                  key={rep.id}
                  onClick={() => toggle(rep.id)}
                  className={cn(
                    "flex items-center gap-3 rounded-2xl border px-3 py-2.5 text-left transition-colors",
                    active ? "border-primary-200 bg-primary-50" : "border-line hover:bg-surface-muted",
                  )}
                >
                  <Avatar name={rep.name} tint={rep.avatarTint} size="sm" status={rep.status} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[13px] font-semibold text-ink">{rep.name}</div>
                    <div className="truncate text-[11px] text-muted">{rep.territory}</div>
                  </div>
                  {active && <Check className="size-4 text-primary-600" />}
                </button>
              );
            })}
          </div>
        </div>

        {error && <p className="rounded-xl bg-rose-50 px-3 py-2 text-[12px] text-[#be123c]">{error}</p>}

        <div className="flex gap-2 pt-1">
          <Button variant="primary" className="flex-1" onClick={submit} disabled={busy || !name.trim()}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : null}
            Create route
          </Button>
          <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
        </div>
      </div>
    </Drawer>
  );
}
