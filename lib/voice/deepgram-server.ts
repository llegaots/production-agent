import "server-only";
import { DeepgramClient } from "@deepgram/sdk";

/** Live STT connection params the browser uses to open the Deepgram WebSocket. */
export const DEEPGRAM_LIVE_PARAMS = {
  model: "nova-3",
  language: "en",
  interim_results: "true",
  diarize: "true",
  punctuate: "true",
  smart_format: "true",
  endpointing: "300",
} as const;

let _client: DeepgramClient | null = null;
function client(): DeepgramClient {
  const apiKey = process.env.DEEPGRAM_API_KEY;
  if (!apiKey) {
    throw new Error("DEEPGRAM_API_KEY is not set — add it to .env.local for live transcription.");
  }
  _client ??= new DeepgramClient({ apiKey });
  return _client;
}

export function isDeepgramConfigured(): boolean {
  return Boolean(process.env.DEEPGRAM_API_KEY);
}

export interface DeepgramCredential {
  /** JWT (scheme "bearer") or raw API key (scheme "token"). */
  token: string;
  /** WebSocket subprotocol scheme: bearer for grant tokens, token for API keys. */
  scheme: "bearer" | "token";
  /** Seconds until expiry; 0 = no expiry (raw key — no refresh needed). */
  expiresIn: number;
}

/** Mint a short-lived credential the rep's browser uses to connect directly to
 *  Deepgram. Preferred path: a scoped JWT via /v1/auth/grant (the API key never
 *  leaves the server; tokens cap at 3600s so a long session refreshes hourly).
 *
 *  If the key is too restricted to mint tokens (no grant / keys:write scope), we
 *  fall back to the raw key **in development only** so testing isn't blocked. In
 *  production a properly-scoped key is required and we throw an actionable error. */
export async function mintDeepgramCredential(ttlSeconds = 3600): Promise<DeepgramCredential> {
  const apiKey = process.env.DEEPGRAM_API_KEY;
  if (!apiKey) throw new Error("DEEPGRAM_API_KEY is not set.");
  try {
    const res = await client().auth.v1.tokens.grant({ ttl_seconds: ttlSeconds });
    return { token: res.access_token, scheme: "bearer", expiresIn: res.expires_in ?? ttlSeconds };
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    if (process.env.NODE_ENV !== "production") {
      console.warn(
        `[deepgram] Couldn't mint an ephemeral token (${msg}). Falling back to the raw ` +
          `API key for the browser — DEV ONLY. For production, use a Deepgram key with the ` +
          `'keys:write' scope (an Owner/Member key) so short-lived tokens can be minted.`,
      );
      return { token: apiKey, scheme: "token", expiresIn: 0 };
    }
    throw new Error(
      "Could not mint a Deepgram token — the DEEPGRAM_API_KEY needs the 'keys:write' scope. " +
        "Create an Owner/Member key in the Deepgram console.",
    );
  }
}
