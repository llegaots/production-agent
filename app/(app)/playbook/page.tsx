import { data } from "@/lib/data";
import { PlaybookView } from "@/components/playbook/playbook-view";

export const dynamic = "force-dynamic";

export default async function PlaybookPage() {
  const [playbook, team] = await Promise.all([data.getPlaybook(), data.getTeam()]);
  return <PlaybookView playbook={playbook} teamId={team?.id ?? null} />;
}
