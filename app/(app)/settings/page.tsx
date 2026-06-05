import { data } from "@/lib/data";
import { SettingsView } from "@/components/settings/settings-view";

export const dynamic = "force-dynamic";

export default async function SettingsPage() {
  const [reps, team] = await Promise.all([data.getReps(), data.getTeam()]);
  const mapsConnected = !!process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY;
  return <SettingsView reps={reps} mapsConnected={mapsConnected} teamId={team?.id ?? null} />;
}
