"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { MapPin, Database, Bell, Building2, Check, ArrowUpRight } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Avatar } from "@/components/ui/avatar";
import { AddMarketerDrawer } from "@/components/team/add-marketer-drawer";
import { fadeInUp, staggerContainer } from "@/lib/motion";
import type { Rep } from "@/lib/types";

function Section({
  icon,
  title,
  desc,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  desc: string;
  children: React.ReactNode;
}) {
  return (
    <motion.div variants={fadeInUp} className="rounded-3xl border border-line bg-surface p-5 shadow-card">
      <div className="mb-4 flex items-center gap-3">
        <span className="grid size-10 place-items-center rounded-2xl bg-primary-50 text-primary-700">
          {icon}
        </span>
        <div>
          <h3 className="text-base font-bold tracking-tight text-ink">{title}</h3>
          <p className="text-[12px] text-muted">{desc}</p>
        </div>
      </div>
      {children}
    </motion.div>
  );
}

function ToggleRow({ label, desc, defaultOn = false }: { label: string; desc: string; defaultOn?: boolean }) {
  const [on, setOn] = useState(defaultOn);
  return (
    <div className="flex items-center justify-between border-b border-line-soft py-3 last:border-0">
      <div>
        <div className="text-[13px] font-medium text-ink">{label}</div>
        <div className="text-[12px] text-muted">{desc}</div>
      </div>
      <Switch checked={on} onCheckedChange={setOn} />
    </div>
  );
}

export function SettingsView({
  reps,
  mapsConnected,
  teamId,
}: {
  reps: Rep[];
  mapsConnected: boolean;
  teamId: string | null;
}) {
  const [addOpen, setAddOpen] = useState(false);
  return (
    <motion.div
      variants={staggerContainer(0.08)}
      initial="hidden"
      animate="show"
      className="mx-auto grid max-w-[1100px] grid-cols-1 gap-5 lg:grid-cols-2"
    >
      <Section icon={<Building2 className="size-5" />} title="Workspace" desc="Your team's profile">
        <div className="flex flex-col gap-3">
          <label className="block">
            <span className="mb-1.5 block text-[12px] font-medium text-ink-soft">Company name</span>
            <Input placeholder="Your company" />
          </label>
          <label className="block">
            <span className="mb-1.5 block text-[12px] font-medium text-ink-soft">Timezone</span>
            <Input defaultValue="America/Toronto (EDT)" />
          </label>
          <Button size="sm" className="mt-1 self-start">
            Save changes
          </Button>
        </div>
      </Section>

      <Section icon={<Bell className="size-5" />} title="Notifications" desc="When to alert managers">
        <ToggleRow label="New lead captured" desc="Ping when an agent auto-detects a lead" defaultOn />
        <ToggleRow label="Rep goes offline" desc="Alert if a live rep drops off mid-shift" defaultOn />
        <ToggleRow label="Grade drops below 75" desc="Coaching flag during a session" />
        <ToggleRow label="Daily summary email" desc="End-of-day performance recap" defaultOn />
      </Section>

      <Section icon={<MapPin className="size-5" />} title="Integrations" desc="Connect maps and your backend">
        <div className="flex flex-col gap-2.5">
          <div className="flex items-center justify-between rounded-2xl border border-line p-3.5">
            <div className="flex items-center gap-3">
              <span className="grid size-9 place-items-center rounded-xl bg-sky-50 text-[#0284c7]">
                <MapPin className="size-4.5" />
              </span>
              <div>
                <div className="text-[13px] font-semibold text-ink">Google Maps</div>
                <div className="text-[11px] text-muted">Routes & live GPS tracking</div>
              </div>
            </div>
            {mapsConnected ? (
              <Badge variant="success" dot>
                Connected
              </Badge>
            ) : (
              <Button size="sm" variant="secondary">
                Add key <ArrowUpRight className="size-3.5" />
              </Button>
            )}
          </div>

          <div className="flex items-center justify-between rounded-2xl border border-line p-3.5">
            <div className="flex items-center gap-3">
              <span className="grid size-9 place-items-center rounded-xl bg-primary-50 text-primary-700">
                <Database className="size-4.5" />
              </span>
              <div>
                <div className="text-[13px] font-semibold text-ink">Supabase</div>
                <div className="text-[11px] text-muted">Database & realtime sync</div>
              </div>
            </div>
            <Badge variant="amber">Coming soon</Badge>
          </div>
        </div>
        {!mapsConnected && (
          <p className="mt-3 rounded-xl bg-surface-muted px-3 py-2 text-[11px] text-muted">
            Add <code className="rounded bg-canvas-deep px-1">NEXT_PUBLIC_GOOGLE_MAPS_API_KEY</code> to{" "}
            <code className="rounded bg-canvas-deep px-1">.env.local</code> to enable live Google Maps.
            Until then a styled preview map is shown.
          </p>
        )}
      </Section>

      <Section icon={<Check className="size-5" />} title="Team members" desc="Who has access">
        <div className="flex flex-col gap-1">
          {reps.length === 0 && (
            <p className="rounded-2xl border border-dashed border-line bg-surface-muted/60 px-3 py-4 text-center text-[12px] text-muted">
              No team members yet. Invite your marketers to get started.
            </p>
          )}
          {reps.map((rep) => (
            <div key={rep.id} className="flex items-center gap-3 border-b border-line-soft py-2.5 last:border-0">
              <Avatar name={rep.name} tint={rep.avatarTint} size="sm" status={rep.status} />
              <div className="min-w-0 flex-1">
                <div className="truncate text-[13px] font-medium text-ink">{rep.name}</div>
                <div className="truncate text-[11px] text-muted">{rep.territory}</div>
              </div>
              <Badge variant="neutral" size="sm">
                Field rep
              </Badge>
            </div>
          ))}
          <Button size="sm" variant="outline" className="mt-2 self-start" onClick={() => setAddOpen(true)}>
            Invite member
          </Button>
        </div>
      </Section>

      <AddMarketerDrawer open={addOpen} onOpenChange={setAddOpen} teamId={teamId} />
    </motion.div>
  );
}
