import { data } from "@/lib/data";
import { KpiRow } from "@/components/dashboard/kpi-row";
import { DoorsChart } from "@/components/dashboard/doors-chart";
import { TopPerformers } from "@/components/dashboard/top-performers";
import { TerritoryTable } from "@/components/dashboard/territory-table";
import { LiveActivity } from "@/components/dashboard/live-activity";
import type { KpiStat } from "@/lib/types";

export const dynamic = "force-dynamic";

const defaultKpis: KpiStat[] = [
  { id: "doors", label: "Doors knocked", value: 0, hint: "today across all reps", tint: "emerald", icon: "DoorOpen" },
  { id: "conversations", label: "Conversations", value: 0, hint: "doors that opened", tint: "sky", icon: "MessagesSquare" },
  { id: "leads", label: "Leads captured", value: 0, hint: "auto-detected today", tint: "violet", icon: "Sparkles" },
  { id: "active", label: "Active reps", value: 0, hint: "live in the field now", tint: "amber", icon: "Radio" },
];

export default async function DashboardPage() {
  const dash = await data.getDashboard();
  const reps = await data.getReps();
  const kpis = dash.kpis.length ? dash.kpis : defaultKpis;

  return (
    <div className="mx-auto flex max-w-[1400px] flex-col gap-5">
      <KpiRow kpis={kpis} />

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
        <div className="xl:col-span-2">
          <DoorsChart data={dash.doorsSeries} />
        </div>
        <TopPerformers reps={reps} />
      </div>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
        <div className="xl:col-span-2">
          <TerritoryTable rows={dash.territoryPerformance} />
        </div>
        <LiveActivity items={dash.liveActivity} />
      </div>
    </div>
  );
}
