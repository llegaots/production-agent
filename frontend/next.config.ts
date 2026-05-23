import type { NextConfig } from "next";
import fs from "fs";
import path from "path";

/** Load repo-root `.env` so frontend shares the same config as the FastAPI backend. */
function loadRootEnv(): Record<string, string> {
  const envPath = path.join(__dirname, "..", ".env");
  if (!fs.existsSync(envPath)) {
    return {};
  }
  const out: Record<string, string> = {};
  for (const line of fs.readFileSync(envPath, "utf8").split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq === -1) continue;
    const key = trimmed.slice(0, eq).trim();
    let val = trimmed.slice(eq + 1).trim();
    if (
      (val.startsWith('"') && val.endsWith('"')) ||
      (val.startsWith("'") && val.endsWith("'"))
    ) {
      val = val.slice(1, -1);
    }
    out[key] = val;
  }
  return out;
}

const rootEnv = loadRootEnv();

const supabaseUrl = rootEnv.SUPABASE_URL ?? process.env.SUPABASE_URL ?? "";
// Browser Supabase client needs a project API key. Prefer explicit anon; otherwise
// use the service role key from the shared root .env (internal dispatcher tooling).
const supabaseBrowserKey =
  rootEnv.SUPABASE_ANON_KEY ??
  rootEnv.SUPABASE_KEY ??
  rootEnv.SUPABASE_SERVICE_KEY ??
  process.env.SUPABASE_ANON_KEY ??
  process.env.SUPABASE_SERVICE_KEY ??
  "";

const apiUrl =
  rootEnv.API_URL ??
  rootEnv.FASTAPI_URL ??
  rootEnv.NEXT_PUBLIC_API_URL ??
  "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  env: {
    NEXT_PUBLIC_SUPABASE_URL: supabaseUrl,
    NEXT_PUBLIC_SUPABASE_ANON_KEY: supabaseBrowserKey,
    NEXT_PUBLIC_API_URL: apiUrl,
  },
};

export default nextConfig;
