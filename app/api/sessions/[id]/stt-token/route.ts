import type { NextRequest } from "next/server";
import { isDeepgramConfigured, mintDeepgramCredential } from "@/lib/voice/deepgram-server";

export const runtime = "nodejs";

/** Mint a short-lived Deepgram token for the rep's browser to stream audio
 *  directly to Deepgram. Called once at session start and refreshed before the
 *  token expires across a long session. */
export async function POST(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  await params; // session id (reserved for future per-session scoping/auditing)
  if (!isDeepgramConfigured()) {
    return Response.json(
      { error: "DEEPGRAM_API_KEY is not set - add it to .env.local for live transcription." },
      { status: 400 },
    );
  }
  try {
    const cred = await mintDeepgramCredential();
    return Response.json(cred);
  } catch (err) {
    return Response.json(
      { error: err instanceof Error ? err.message : "Could not mint Deepgram token" },
      { status: 500 },
    );
  }
}
