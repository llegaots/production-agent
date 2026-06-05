import { data } from "@/lib/data";
import { CoverageView } from "@/components/coverage/coverage-view";

export const dynamic = "force-dynamic";

export default async function CoveragePage() {
  const [routes, doors] = await Promise.all([data.getRoutes(), data.getAllDoors()]);
  return <CoverageView routes={routes} doors={doors} />;
}
