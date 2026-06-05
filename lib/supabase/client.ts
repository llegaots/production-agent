"use client";

import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const anon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

let _client: SupabaseClient | null = null;

/** Browser client for Realtime. Null when the anon key isn't set — callers
 *  should fall back to polling the generation status endpoint. */
export function supabaseBrowser(): SupabaseClient | null {
  if (!url || !anon) return null;
  _client ??= createClient(url, anon, { auth: { persistSession: false } });
  return _client;
}
