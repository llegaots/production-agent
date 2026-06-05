import type { NextRequest } from "next/server";
import { supabaseAdmin, isSupabaseConfigured } from "@/lib/supabase/server";
import { refinePreview } from "@/lib/agent/refine";
import type { GeoCache } from "@/lib/agent/preview";
import type { RoutePreview } from "@/lib/types";

export const runtime = "nodejs";
export const maxDuration = 120;

export async function POST(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  if (!isSupabaseConfigured()) {
    return Response.json({ error: "Supabase is not configured." }, { status: 400 });
  }
  if (!process.env.ANTHROPIC_API_KEY) {
    return Response.json({ error: "ANTHROPIC_API_KEY is not set." }, { status: 400 });
  }
  const { id } = await params;
  let body: { message?: string };
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: "Invalid JSON" }, { status: 400 });
  }
  const message = body.message?.trim();
  if (!message) return Response.json({ error: "A message is required." }, { status: 400 });

  const db = supabaseAdmin();
  const { data: row, error } = await db
    .from("D2D_RouteGenerations")
    .select("status,preview,geo_cache")
    .eq("id", id)
    .maybeSingle();
  if (error) return Response.json({ error: error.message }, { status: 500 });
  if (!row) return Response.json({ error: "Generation not found." }, { status: 404 });
  if (row.status === "confirmed") return Response.json({ error: "This plan is already scheduled." }, { status: 400 });

  const cache = row.geo_cache as GeoCache | null;
  const preview = row.preview as RoutePreview | null;
  if (!cache || !preview) {
    return Response.json({ error: "No preview to refine — regenerate first." }, { status: 400 });
  }

  try {
    const { preview: next, reply } = await refinePreview(cache, preview, message);
    await db.from("D2D_RouteGenerations").update({ preview: next }).eq("id", id);
    return Response.json({ preview: next, reply });
  } catch (e) {
    return Response.json({ error: e instanceof Error ? e.message : String(e) }, { status: 500 });
  }
}
