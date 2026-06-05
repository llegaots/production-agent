import { data } from "@/lib/data";
import { SessionsGrid } from "@/components/sessions/sessions-grid";
import { SessionHistory } from "@/components/sessions/session-history";
import { DemoButton } from "@/components/sessions/demo-button";

export const dynamic = "force-dynamic";

export default async function SessionsPage() {
  const [live, recent] = await Promise.all([data.getLiveSessions(), data.getRecentSessions()]);
  const initialLines = await data.getLatestLines(live.map((s) => s.id));
  return (
    <div className="flex flex-col gap-6">
      <div className="mx-auto flex w-full max-w-[1400px] items-start justify-between gap-3">
        <p className="max-w-[60ch] text-[13px] text-muted">
          Watch the team in the field in real time. No phones handy? Press{" "}
          <span className="font-semibold text-ink-soft">Start live demo</span> to play the seeded
          CrystalClear crew walking their routes - live GPS, transcripts, detected leads and playbook grading.
          The crew keeps walking for about 10 minutes, or until you press Stop demo.
        </p>
        <DemoButton running={live.length > 0} />
      </div>
      <SessionsGrid sessions={live} initialLines={initialLines} />
      <div className="mx-auto w-full max-w-[1400px]">
        <SessionHistory sessions={recent} />
      </div>
    </div>
  );
}
