import "server-only";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

/** True when at least reads are possible. */
export function isSupabaseConfigured(): boolean {
  return Boolean(url && (serviceKey || anonKey));
}

let _admin: SupabaseClient | null = null;
/** Privileged server client (bypasses RLS) - Route Handlers / writes only. */
export function supabaseAdmin(): SupabaseClient {
  if (!url || !serviceKey) {
    throw new Error(
      "Supabase admin not configured - set NEXT_PUBLIC_SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env.local",
    );
  }
  _admin ??= createClient(url, serviceKey, { auth: { persistSession: false } });
  return _admin;
}

let _read: SupabaseClient | null = null;
/** Read client for server components / the data layer. Prefers the anon key
 *  (respects RLS); falls back to the service key. Returns null if unconfigured. */
export function supabaseRead(): SupabaseClient | null {
  if (!url) return null;
  const key = anonKey || serviceKey;
  if (!key) return null;
  _read ??= createClient(url, key, { auth: { persistSession: false } });
  return _read;
}
