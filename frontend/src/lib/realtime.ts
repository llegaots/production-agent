import type { SupabaseClient } from "@supabase/supabase-js";

/** Subscribe to Postgres changes and reload from Supabase (no localStorage cache). */
export function subscribeTable(
  supabase: SupabaseClient,
  channelName: string,
  table: string,
  filter: string | undefined,
  onChange: () => void,
) {
  const channel = supabase.channel(channelName);
  const config: {
    event: "*";
    schema: "public";
    table: string;
    filter?: string;
  } = { event: "*", schema: "public", table };
  if (filter) config.filter = filter;

  channel.on("postgres_changes", config, () => onChange()).subscribe();
  return () => {
    void supabase.removeChannel(channel);
  };
}
