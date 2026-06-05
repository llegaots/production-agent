import { data } from "@/lib/data";
import { StartSession } from "@/components/record/start-session";

export const dynamic = "force-dynamic";

/** Rep-facing landing screen (mobile/PWA). The rep picks themselves and starts a
 *  recording session, which streams a live transcript to their manager. */
export default async function RecordPage() {
  const [reps, team] = await Promise.all([data.getReps(), data.getTeam()]);
  return (
    <main className="mx-auto flex min-h-dvh max-w-lg flex-col gap-6 px-5 py-8">
      <header className="flex flex-col gap-1">
        <span className="text-[13px] font-semibold uppercase tracking-wide text-primary-600">
          RouteIQ · Field
        </span>
        <h1 className="font-display text-2xl font-extrabold tracking-tight text-ink">
          Start your session
        </h1>
        <p className="text-sm text-muted">
          Pick your name to begin. We&apos;ll record and transcribe your shift live so your
          manager can follow along and your leads get captured automatically.
        </p>
      </header>
      <StartSession reps={reps} teamId={team?.id ?? null} />
    </main>
  );
}
