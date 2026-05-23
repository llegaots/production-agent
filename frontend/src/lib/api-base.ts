/**
 * Browser: same-origin `/api` (proxied to FastAPI via next.config rewrites).
 * Server: direct backend URL from env.
 */
export function getApiBase(): string {
  if (typeof window !== "undefined") {
    return "/api";
  }
  const url = process.env.NEXT_PUBLIC_API_URL?.trim();
  return url || "http://127.0.0.1:8000";
}
