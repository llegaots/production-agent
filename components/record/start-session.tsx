"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Mic } from "lucide-react";
import { Avatar } from "@/components/ui/avatar";
import type { Rep } from "@/lib/types";

/** Rep picker → creates a live session and routes to the capture screen. */
export function StartSession({ reps, teamId }: { reps: Rep[]; teamId: string | null }) {
  const router = useRouter();
  const [startingId, setStartingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function start(rep: Rep) {
    setError(null);
    setStartingId(rep.id);
    try {
      const res = await fetch("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ marketerId: rep.id, teamId, territory: rep.territory }),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.error || "Could not start session.");
      router.push(`/record/${json.sessionId}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start session.");
      setStartingId(null);
    }
  }

  if (!reps.length) {
    return (
      <p className="rounded-2xl border border-line bg-surface p-4 text-sm text-muted">
        No reps found. Add marketers (and configure Supabase) first.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {error && (
        <p className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-[13px] text-[#be123c]">
          {error}
        </p>
      )}
      <ul className="flex flex-col gap-2.5">
        {reps.map((rep) => {
          const busy = startingId === rep.id;
          return (
            <li key={rep.id}>
              <button
                disabled={startingId !== null}
                onClick={() => start(rep)}
                className="flex w-full items-center gap-3 rounded-2xl border border-line bg-surface p-3.5 text-left shadow-soft transition-all duration-200 hover:border-primary-200 hover:bg-surface-muted active:scale-[0.99] disabled:opacity-60"
              >
                <Avatar name={rep.name} tint={rep.avatarTint} size="lg" />
                <div className="min-w-0 flex-1">
                  <p className="truncate font-semibold text-ink">{rep.name}</p>
                  <p className="truncate text-[13px] text-muted">{rep.territory || "—"}</p>
                </div>
                <span className="grid size-9 shrink-0 place-items-center rounded-full bg-primary-50 text-primary-600">
                  {busy ? <Loader2 className="size-4 animate-spin" /> : <Mic className="size-4" />}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
