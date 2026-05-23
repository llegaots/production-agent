/** Supabase + API env (from repo-root `.env` via next.config.ts). */

export function getSupabaseConfig() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL?.trim() ?? "";
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY?.trim() ?? "";
  return { url, anonKey };
}

export function getApiUrl() {
  return process.env.NEXT_PUBLIC_API_URL?.trim() || "http://127.0.0.1:8000";
}

export function supabaseConfigError(): string | null {
  const { url, anonKey } = getSupabaseConfig();
  if (!url) {
    return "Missing SUPABASE_URL in repo-root .env";
  }
  if (!anonKey) {
    return "Missing SUPABASE_SERVICE_KEY (or SUPABASE_ANON_KEY) in repo-root .env";
  }
  if (!url.includes("supabase.co")) {
    return "SUPABASE_URL does not look like a Supabase project URL.";
  }
  return null;
}
