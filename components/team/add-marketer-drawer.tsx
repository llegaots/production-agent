"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { UserPlus, Loader2 } from "lucide-react";
import { Drawer } from "@/components/ui/drawer";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { tints, tintList } from "@/components/ui/tint";
import { Field } from "@/components/ui/field";
import type { AccentTint } from "@/lib/types";

export function AddMarketerDrawer({
  open,
  onOpenChange,
  teamId,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  teamId: string | null;
}) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [territory, setTerritory] = useState("");
  const [tint, setTint] = useState<AccentTint>("emerald");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const reset = () => {
    setName("");
    setEmail("");
    setPhone("");
    setTerritory("");
    setTint("emerald");
    setError("");
  };

  async function submit() {
    if (!name.trim()) return;
    setBusy(true);
    setError("");
    try {
      const res = await fetch("/api/marketers", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ name, email, phone, territory, avatar_tint: tint, team_id: teamId }),
      });
      const json = await res.json();
      if (!res.ok) {
        setError(json.error ?? "Could not add marketer");
        return;
      }
      reset();
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
      title="Add a marketer"
      description="Add a field rep to your team"
      widthClass="max-w-md"
    >
      <div className="flex flex-col gap-5 p-6">
        <Field label="Full name">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Jordan Lee" autoFocus />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Email">
            <Input value={email} onChange={(e) => setEmail(e.target.value)} type="email" placeholder="jordan@team.co" />
          </Field>
          <Field label="Phone">
            <Input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="(416) 555-0100" />
          </Field>
        </div>
        <Field label="Home territory">
          <Input value={territory} onChange={(e) => setTerritory(e.target.value)} placeholder="e.g. Leslieville" />
        </Field>

        <div>
          <span className="mb-2 block text-[12px] font-medium text-ink-soft">Avatar colour</span>
          <div className="flex gap-2">
            {tintList.map((t) => (
              <button
                key={t}
                onClick={() => setTint(t)}
                className={cn(
                  "size-8 rounded-full ring-2 ring-offset-2 ring-offset-surface transition-all",
                  tints[t].solid,
                  tint === t ? "ring-ink/30 scale-110" : "ring-transparent",
                )}
                aria-label={t}
              />
            ))}
          </div>
        </div>

        {error && <p className="rounded-xl bg-rose-50 px-3 py-2 text-[12px] text-[#be123c]">{error}</p>}

        <div className="flex gap-2 pt-1">
          <Button className="flex-1" onClick={submit} disabled={busy || !name.trim()}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : <UserPlus className="size-4" />}
            Add marketer
          </Button>
          <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
        </div>
      </div>
    </Drawer>
  );
}
