import { data } from "@/lib/data";
import { SessionsGrid } from "@/components/sessions/sessions-grid";
import { SessionHistory } from "@/components/sessions/session-history";

export const dynamic = "force-dynamic";

export default async function SessionsPage() {
  const [live, recent] = await Promise.all([data.getLiveSessions(), data.getRecentSessions()]);
  return (
    <div className="flex flex-col gap-6">
      <SessionsGrid sessions={live} />
      <div className="mx-auto w-full max-w-[1400px]">
        <SessionHistory sessions={recent} />
      </div>
    </div>
  );
}
