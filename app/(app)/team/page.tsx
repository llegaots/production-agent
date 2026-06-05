import { data } from "@/lib/data";
import { TeamView } from "@/components/team/team-view";

export const dynamic = "force-dynamic";

export default async function TeamPage() {
  const [reps, team, routes, shifts] = await Promise.all([
    data.getReps(),
    data.getTeam(),
    data.getRoutes(),
    data.getShifts(),
  ]);
  return <TeamView reps={reps} teamId={team?.id ?? null} routes={routes} shifts={shifts} />;
}
