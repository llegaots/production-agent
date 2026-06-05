import { data } from "@/lib/data";
import { ScheduleView } from "@/components/schedule/schedule-view";

export const dynamic = "force-dynamic";

export default async function SchedulePage() {
  const [shifts, reps, routes] = await Promise.all([
    data.getShifts(),
    data.getReps(),
    data.getRoutes(),
  ]);
  return <ScheduleView initialShifts={shifts} reps={reps} routes={routes} />;
}
