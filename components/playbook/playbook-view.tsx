"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { Sparkles, Plus, ShieldAlert, Save, Scale, BookOpenText, Loader2, X, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { EmptyState } from "@/components/ui/empty-state";
import { fadeInUp, staggerContainer } from "@/lib/motion";
import type { Objection, Playbook } from "@/lib/types";

const catVariant: Record<Objection["category"], BadgeProps["variant"]> = {
  price: "amber",
  timing: "sky",
  trust: "violet",
  need: "emerald",
  authority: "rose",
  stall: "neutral",
};
const CATEGORIES: Objection["category"][] = ["price", "timing", "trust", "need", "authority", "stall"];

const STARTER: Playbook = {
  scriptTitle: "Cold Approach Script",
  script: `OPENER
"Hi there - I'm {name} with {company}, I'm in the neighbourhood today. Quick question..."

DISCOVERY
-

VALUE
-

CLOSE
"I've got {time A} or {time B} - which is easier?"`,
  objections: [
    { id: "obj-1", trigger: "It's too expensive", category: "price", handle: "Acknowledge, reframe to cost of inaction, offer the free check.", frequency: 0, successRate: 0 },
    { id: "obj-2", trigger: "Not right now", category: "timing", handle: "Micro-commit: 'It only takes 10 minutes and you don't need to be home.'", frequency: 0, successRate: 0 },
  ],
  gradingCriteria: [
    { id: "crit-open", label: "Opener strength", weight: 20, description: "Pattern interrupt + permission-based question." },
    { id: "crit-discovery", label: "Discovery quality", weight: 20, description: "Uncovers pain + decision-maker before pitching." },
    { id: "crit-objection", label: "Objection handling", weight: 25, description: "Acknowledges, reframes, re-asks for the micro-commit." },
    { id: "crit-tone", label: "Tone & rapport", weight: 15, description: "Warm, unhurried, no pressure spikes." },
    { id: "crit-close", label: "Close discipline", weight: 20, description: "Always offers a specific two-option appointment." },
  ],
};

export function PlaybookView({ playbook, teamId }: { playbook: Playbook | null; teamId: string | null }) {
  const router = useRouter();
  const [creating, setCreating] = useState(false);

  async function persist(p: Playbook) {
    await fetch("/api/playbook", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ teamId, ...p }),
    });
  }

  if (!playbook) {
    return (
      <div className="mx-auto max-w-[1100px]">
        <div className="rounded-3xl border border-line bg-surface shadow-card">
          <EmptyState
            icon={<BookOpenText className="size-6" />}
            title="No playbook yet"
            description="Start your cold-approach script and map the common objections + handles. This is exactly what your AI agents grade every conversation against."
            action={
              <Button
                size="sm"
                disabled={creating}
                onClick={async () => {
                  setCreating(true);
                  await persist(STARTER);
                  router.refresh();
                }}
              >
                {creating ? <Loader2 className="size-4 animate-spin" /> : <Plus className="size-4" />} Create your script
              </Button>
            }
          />
        </div>
      </div>
    );
  }

  return <PlaybookEditor playbook={playbook} onSave={persist} />;
}

function PlaybookEditor({ playbook, onSave }: { playbook: Playbook; onSave: (p: Playbook) => Promise<void> }) {
  const router = useRouter();
  const [title, setTitle] = useState(playbook.scriptTitle);
  const [script, setScript] = useState(playbook.script);
  const [objections, setObjections] = useState<Objection[]>(playbook.objections);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const save = async () => {
    setSaving(true);
    setSaved(false);
    await onSave({ scriptTitle: title, script, objections, gradingCriteria: playbook.gradingCriteria });
    setSaving(false);
    setSaved(true);
    router.refresh();
    setTimeout(() => setSaved(false), 2000);
  };

  const setObj = (id: string, patch: Partial<Objection>) =>
    setObjections((prev) => prev.map((o) => (o.id === id ? { ...o, ...patch } : o)));
  const addObj = () =>
    setObjections((prev) => [
      ...prev,
      { id: `obj-${Date.now()}`, trigger: "New objection", category: "stall", handle: "", frequency: 0, successRate: 0 },
    ]);
  const cycleCat = (id: string, cur: Objection["category"]) =>
    setObj(id, { category: CATEGORIES[(CATEGORIES.indexOf(cur) + 1) % CATEGORIES.length] });

  return (
    <div className="mx-auto flex max-w-[1400px] flex-col gap-5">
      <motion.div
        variants={fadeInUp}
        initial="hidden"
        animate="show"
        className="flex items-center gap-3 rounded-3xl border border-primary-100 bg-gradient-to-br from-primary-50/70 to-surface p-4"
      >
        <span className="grid size-10 shrink-0 place-items-center rounded-2xl bg-primary-100 text-primary-700">
          <Sparkles className="size-5" />
        </span>
        <p className="text-[13px] leading-relaxed text-ink-soft">
          Your AI agents grade every conversation against this script and these objection handles in real
          time. Keep it sharp - changes apply to all live sessions instantly.
        </p>
      </motion.div>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-12">
        <div className="flex flex-col gap-5 xl:col-span-7">
          <div className="rounded-3xl border border-line bg-surface p-5 shadow-card">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <h3 className="text-base font-bold tracking-tight text-ink">Main script</h3>
                <p className="text-[12px] text-muted">The flow reps are coached to run</p>
              </div>
              <Button size="sm" onClick={save} disabled={saving}>
                {saving ? <Loader2 className="size-4 animate-spin" /> : saved ? <Check className="size-4" /> : <Save className="size-4" />}
                {saved ? "Saved" : "Save"}
              </Button>
            </div>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} className="mb-3 font-semibold" />
            <Textarea value={script} onChange={(e) => setScript(e.target.value)} rows={16} className="font-mono text-[12.5px] leading-relaxed" />
          </div>

          <div className="rounded-3xl border border-line bg-surface p-5 shadow-card">
            <div className="mb-4 flex items-center gap-2">
              <Scale className="size-4 text-primary-600" />
              <h3 className="text-base font-bold tracking-tight text-ink">Grading criteria</h3>
            </div>
            <div className="flex flex-col gap-3.5">
              {playbook.gradingCriteria.map((c) => (
                <div key={c.id}>
                  <div className="mb-1 flex items-center justify-between">
                    <span className="text-[13px] font-semibold text-ink">{c.label}</span>
                    <span className="nums text-[12px] font-bold text-primary-700">{c.weight}%</span>
                  </div>
                  <Progress value={c.weight * 2.5} height="h-1.5" />
                  <p className="mt-1 text-[12px] text-muted">{c.description}</p>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="xl:col-span-5">
          <div className="flex h-full flex-col rounded-3xl border border-line bg-surface shadow-card">
            <div className="flex items-center justify-between border-b border-line p-5">
              <div className="flex items-center gap-2">
                <ShieldAlert className="size-4 text-[#b45309]" />
                <div>
                  <h3 className="text-base font-bold tracking-tight text-ink">Objection handles</h3>
                  <p className="text-[12px] text-muted">{objections.length} mapped responses</p>
                </div>
              </div>
              <Button size="sm" onClick={addObj}>
                <Plus className="size-4" /> Add
              </Button>
            </div>

            <motion.div variants={staggerContainer(0.05)} initial="hidden" animate="show" className="flex flex-col gap-3 p-4">
              {objections.map((obj) => (
                <motion.div key={obj.id} variants={fadeInUp} className="rounded-2xl border border-line-soft bg-surface-muted/50 p-3.5">
                  <div className="flex items-start gap-2">
                    <Input
                      value={obj.trigger}
                      onChange={(e) => setObj(obj.id, { trigger: e.target.value })}
                      className="h-8 flex-1 bg-surface text-[13px] font-semibold"
                      placeholder="Objection (e.g. too expensive)"
                    />
                    <button onClick={() => cycleCat(obj.id, obj.category)} title="Change category">
                      <Badge variant={catVariant[obj.category]} size="sm">
                        {obj.category}
                      </Badge>
                    </button>
                    <button
                      onClick={() => setObjections((prev) => prev.filter((o) => o.id !== obj.id))}
                      className="grid size-6 shrink-0 place-items-center rounded-md text-faint hover:bg-rose-50 hover:text-[#be123c]"
                    >
                      <X className="size-3.5" />
                    </button>
                  </div>
                  <Textarea
                    value={obj.handle}
                    onChange={(e) => setObj(obj.id, { handle: e.target.value })}
                    rows={2}
                    className="mt-2 bg-surface text-[12.5px]"
                    placeholder="How the rep should respond…"
                  />
                </motion.div>
              ))}
            </motion.div>
          </div>
        </div>
      </div>
    </div>
  );
}
