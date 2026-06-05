import { after, type NextRequest } from "next/server";
import { supabaseAdmin, isSupabaseConfigured } from "@/lib/supabase/server";
import { runRoutePlanner, type PlannerMarketer } from "@/lib/agent/route-planner";
import { shiftHours } from "@/lib/geo/capacity";

export const runtime = "nodejs";
export const maxDuration = 300;

interface GenerateBody {
  area: string;
  date: string;
  teamId?: string | null;
  sessionHours?: number;
  minPerDoor?: number;
  walkKmh?: number;
  avoidDays?: number;
  marketers: { id: string; name: string; territory?: string; start: string; end: string }[];
}

export async function POST(req: NextRequest) {
  if (!isSupabaseConfigured()) {
    return Response.json({ error: "Supabase is not configured (.env.local)." }, { status: 400 });
  }
  if (!process.env.ANTHROPIC_API_KEY) {
    return Response.json(
      { error: "ANTHROPIC_API_KEY is not set — add it to .env.local to run the planner." },
      { status: 400 },
    );
  }

  let body: GenerateBody;
  try {
    body = (await req.json()) as GenerateBody;
  } catch {
    return Response.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const area = body.area?.trim();
  if (!area) return Response.json({ error: "An area (postal code or place) is required." }, { status: 400 });
  if (!body.marketers?.length)
    return Response.json({ error: "At least one marketer is required." }, { status: 400 });

  const minPerDoor = body.minPerDoor && body.minPerDoor > 0 ? body.minPerDoor : 2;
  const walkKmh = body.walkKmh && body.walkKmh > 0 ? body.walkKmh : 4.5;
  const sessionHours = body.sessionHours && body.sessionHours > 0 ? body.sessionHours : 4;
  const avoidDays = body.avoidDays ?? 60;
  const date = body.date || new Date().toISOString().slice(0, 10);

  const marketers: PlannerMarketer[] = body.marketers.map((m) => ({
    id: m.id,
    name: m.name,
    territory: m.territory ?? "",
    start: m.start,
    end: m.end,
    hours: shiftHours(m.start, m.end) || 4,
  }));

  const db = supabaseAdmin();
  const { data: gen, error } = await db
    .from("D2D_RouteGenerations")
    .insert({
      team_id: body.teamId ?? null,
      area_input: area,
      params: { date, sessionHours, minPerDoor, walkKmh, avoidDays, marketerCount: marketers.length },
      status: "queued",
      stage: "Queued",
      progress: 5,
    })
    .select("id")
    .single();

  if (error || !gen) {
    return Response.json({ error: error?.message ?? "Could not create generation" }, { status: 500 });
  }
  const generationId = gen.id as string;

  after(async () => {
    const update = (fields: Record<string, unknown>) =>
      db.from("D2D_RouteGenerations").update(fields).eq("id", generationId);
    try {
      await update({ status: "running", stage: "Starting", progress: 8 });
      const result = await runRoutePlanner(
        {
          area,
          date,
          marketers,
          avoidDays,
          teamId: body.teamId ?? null,
          generationId,
          timePerDoorSec: minPerDoor * 60,
          walkSpeedMps: walkKmh / 3.6,
          sessionHours,
        },
        { onStage: async (stage, progress) => void (await update({ stage, progress })) },
      );
      if (!result.preview || !result.geoCache) {
        await update({
          status: "error",
          stage: "Error",
          error: result.summary || "The planner did not produce any routes.",
          completed_at: new Date().toISOString(),
        });
        return;
      }
      await update({
        status: "preview",
        stage: "Ready to review",
        progress: 100,
        agent_summary: result.summary,
        preview: result.preview,
        geo_cache: result.geoCache,
      });
    } catch (err) {
      await update({
        status: "error",
        stage: "Error",
        error: err instanceof Error ? err.message : String(err),
        completed_at: new Date().toISOString(),
      });
    }
  });

  return Response.json({ generationId });
}
