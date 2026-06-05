import { data } from "@/lib/data";
import { RoutesView } from "@/components/routes/routes-view";

export const dynamic = "force-dynamic";

export default async function RoutesPage() {
  const [routes, reps, shifts, team] = await Promise.all([
    data.getRoutes(),
    data.getReps(),
    data.getShifts(),
    data.getTeam(),
  ]);
  return <RoutesView routes={routes} reps={reps} shifts={shifts} teamId={team?.id ?? null} />;
}
