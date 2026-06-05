import { data } from "@/lib/data";
import { CoverageView } from "@/components/coverage/coverage-view";

export const dynamic = "force-dynamic";

export default async function CoveragePage() {
  const routes = await data.getRoutes();
  return <CoverageView routes={routes} />;
}
