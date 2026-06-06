import "server-only";
import Anthropic from "@anthropic-ai/sdk";
import { MODEL, anthropic } from "./client";
import { supabaseAdmin } from "@/lib/supabase/server";
import { geocodeArea } from "@/lib/geo/geocode";
import { fetchAreaData } from "@/lib/geo/overpass";
import { filterCoveredSegments } from "@/lib/geo/path";
import type { PaceModel } from "@/lib/geo/capacity";
import { clampBounds } from "@/lib/geo/util";
import { planPreview, type GeoCache } from "./preview";
import type { GeoBounds, StreetSegment } from "@/lib/geo/types";
import type { LatLng, RoutePreview } from "@/lib/types";

export interface PlannerMarketer {
  id: string;
  name: string;
  territory: string;
  start: string;
  end: string;
  hours: number;
}

export interface PlannerInput {
  area: string;
  date: string;
  marketers: PlannerMarketer[];
  avoidDays: number;
  teamId: string | null;
  generationId: string;
  timePerDoorSec: number;
  walkSpeedMps: number;
  sessionHours?: number;
  /** coordinates from a picked place, so we skip geocoding a bare postal code */
  center?: LatLng;
  bounds?: GeoBounds;
}

export interface PlannerHooks {
  onStage: (stage: string, progress: number) => Promise<void>;
}

export interface PlannerResult {
  summary: string;
  preview: RoutePreview | null;
  geoCache: GeoCache | null;
}

interface Ctx {
  input: PlannerInput;
  pace: PaceModel;
  bounds?: GeoBounds;
  center?: LatLng;
  polygon?: LatLng[][];
  displayName?: string;
  streets: StreetSegment[];
  homes: LatLng[];
  pastLines: LatLng[][];
  preview: RoutePreview | null;
  geoCache: GeoCache | null;
  summary: string;
}

const SYSTEM = `You are RouteIQ's field route planner. You design door-to-door walking routes for a team working ONE session in a target area, then save them.

Hard rules:
- Marketers ALWAYS work in PAIRS on the same route - nobody walks alone. Routes = floor(marketers / 2). An odd leftover joins the nearest pair as a trio - never a solo route.
- Each route is an OPEN walking trail of UNIQUE streets - the pair walks together (one per side), covering each street in a SINGLE pass with minimal re-walking. It does NOT need to return to the start. Long cul-de-sacs are deferred to a later cleanup session rather than forcing backtracking. The tools build this.
- Routes are sized by the SESSION LENGTH in hours, using REAL home counts (OSM buildings) and parallel knocking (the pair splits the doors, one per side) plus walking time. Do not invent door counts - the tools count actual homes.
- Coverage is CONTIGUOUS and tight around the target center - pairs work adjacent zones with near-zero travel between them. Never spread across barriers (rivers/highways).
- Stay INSIDE the target postal code - the tools clip streets/homes to its boundary.
- Only residential streets that front homes are used.

Process - call tools in order:
1. geocode_area - resolve the postal code to a center, bounds, and (if available) its boundary.
2. fetch_area - pull residential streets + home footprints, clipped to the postal code.
3. get_past_coverage - drop streets covered recently (use the avoid window).
4. propose_routes - pass the pairings (groups of marketer ids). The tool sizes each route to the session length from real homes, grows one contiguous area from the center, splits into adjacent zones, builds street-following trails, and names each from real streets. This produces a PREVIEW for the manager to review - nothing is scheduled yet. The manager can then chat to refine it and Confirm to schedule.

After it returns, reply with a short manager-facing summary (2-4 sentences): the pairings, the territory each got, real doors + minutes each, and that this is a preview they can refine in chat (e.g. "make Zone A bigger" or "cover Main St instead") before confirming.
Write the summary in plain text: never use em dashes or en dashes; use commas, periods, parentheses, or a normal hyphen instead.`;

const tools: Anthropic.Tool[] = [
  {
    name: "geocode_area",
    description: "Resolve the target area (postal code / place) to a center and bounding box.",
    input_schema: { type: "object", properties: { area: { type: "string" } }, required: ["area"] },
  },
  {
    name: "fetch_area",
    description: "Fetch the residential street network and home building footprints in the area. Call after geocode_area.",
    input_schema: { type: "object", properties: {}, required: [] },
  },
  {
    name: "get_past_coverage",
    description: "Drop streets covered by routes in the last `sinceDays` days so they aren't re-assigned.",
    input_schema: { type: "object", properties: { sinceDays: { type: "number" } }, required: ["sinceDays"] },
  },
  {
    name: "propose_routes",
    description:
      "Size and plan one route per pair, producing a PREVIEW (not saved). Provide the pairings as groups of marketer ids. The tool counts real homes, sizes each route to the session length, builds contiguous adjacent zones with street-following trails, and names them.",
    input_schema: {
      type: "object",
      properties: {
        groups: {
          type: "array",
          description: "One entry per pair - each group is 2 (or 3) marketer ids who walk a route together.",
          items: {
            type: "object",
            properties: { marketerIds: { type: "array", items: { type: "string" } } },
            required: ["marketerIds"],
          },
        },
      },
      required: ["groups"],
    },
  },
];

async function execute(name: string, input: unknown, ctx: Ctx, hooks: PlannerHooks): Promise<unknown> {
  switch (name) {
    case "geocode_area": {
      await hooks.onStage("Geocoding postal code", 12);
      // Coordinates already supplied by the picked place - use them directly.
      if (ctx.center && ctx.bounds) {
        return {
          displayName: ctx.displayName ?? ctx.input.area,
          center: ctx.center,
          bounds: ctx.bounds,
          hasBoundary: false,
          note: "Using the coordinates from the selected place.",
        };
      }
      const { area } = input as { area: string };
      const geo = await geocodeArea(area || ctx.input.area);
      ctx.bounds = clampBounds(geo.bounds, 4);
      ctx.center = geo.center;
      ctx.polygon = geo.polygon;
      ctx.displayName = geo.displayName;
      return {
        displayName: geo.displayName,
        center: geo.center,
        bounds: ctx.bounds,
        hasBoundary: Boolean(geo.polygon?.length),
        note: geo.polygon?.length
          ? "Found the postal code boundary - coverage will be clipped to inside it."
          : "No exact boundary in OSM - using the postal code's bounding box.",
      };
    }
    case "fetch_area": {
      await hooks.onStage("Fetching homes & streets", 35);
      if (!ctx.bounds) return { error: "Call geocode_area first" };
      const { streets, homes } = await fetchAreaData(ctx.bounds, ctx.polygon);
      ctx.streets = streets;
      ctx.homes = homes;
      const names = [...new Set(streets.map((s) => s.name).filter(Boolean))].slice(0, 25);
      return { residentialStreetCount: streets.length, homeCount: homes.length, clippedToPostalCode: Boolean(ctx.polygon?.length), sampleStreetNames: names };
    }
    case "get_past_coverage": {
      await hooks.onStage("Checking past coverage", 55);
      const { sinceDays } = input as { sinceDays: number };
      if (!ctx.bounds) return { error: "Call geocode_area first" };
      const db = supabaseAdmin();
      const { data, error } = await db.rpc("d2d_recent_coverage", {
        min_lng: ctx.bounds.minLng,
        min_lat: ctx.bounds.minLat,
        max_lng: ctx.bounds.maxLng,
        max_lat: ctx.bounds.maxLat,
        since_days: Math.max(1, Math.round(sinceDays || 60)),
      });
      if (error) return { error: error.message };
      const rows = (data ?? []) as { name: string; coverage_geojson: string }[];
      ctx.pastLines = rows
        .map((r) => {
          try {
            const gj = JSON.parse(r.coverage_geojson) as { type: string; coordinates: number[][] | number[][][] };
            const coords = gj.type === "MultiLineString" ? (gj.coordinates as number[][][]).flat() : (gj.coordinates as number[][]);
            return coords.map(([lng, lat]) => ({ lat, lng }));
          } catch {
            return [];
          }
        })
        .filter((l) => l.length > 0);
      const before = ctx.streets.length;
      ctx.streets = filterCoveredSegments(ctx.streets, ctx.pastLines);
      return { pastRouteCount: rows.length, removedStreets: before - ctx.streets.length, remainingStreets: ctx.streets.length };
    }
    case "propose_routes": {
      await hooks.onStage("Planning routes", 78);
      const { groups } = input as { groups: { marketerIds: string[] }[] };
      if (!ctx.center || !ctx.bounds) return { error: "No center - call geocode_area first" };
      if (!ctx.streets.length) return { error: "No residential streets available in this area" };

      const hoursById = new Map(ctx.input.marketers.map((m) => [m.id, m.hours]));
      const validGroups = groups
        .map((g) => g.marketerIds.filter((id) => hoursById.has(id)))
        .filter((ids) => ids.length > 0);
      if (!validGroups.length) return { error: "No valid marketer groups provided" };

      const budgetsBaseSec = validGroups.map((ids) => {
        const pairHours = Math.min(...ids.map((id) => hoursById.get(id) ?? 4));
        const hrs = ctx.input.sessionHours && ctx.input.sessionHours > 0 ? Math.min(ctx.input.sessionHours, pairHours || ctx.input.sessionHours) : pairHours;
        return Math.max(0.5, hrs) * 3600;
      });

      const cache: GeoCache = {
        area: ctx.input.area,
        date: ctx.input.date,
        displayName: ctx.displayName ?? ctx.input.area,
        center: ctx.center,
        bounds: ctx.bounds,
        streets: ctx.streets,
        homes: ctx.homes,
        marketers: ctx.input.marketers,
        groups: validGroups,
        budgetsBaseSec,
        pace: ctx.pace,
      };

      const { routes, totalHomes } = planPreview(cache);
      if (!routes.length) return { error: "Could not build any routes from the available streets" };

      await hooks.onStage("Building preview", 92);
      ctx.geoCache = cache;
      ctx.preview = { area: ctx.input.area, date: ctx.input.date, totalHomes, routes, chat: [] };

      return {
        proposedRoutes: routes.map((r) => ({ name: r.name, doors: r.doors, minutes: r.minutes, marketers: r.marketerNames })),
        totalHomesInArea: totalHomes,
        count: routes.length,
        note: "Preview built - not scheduled yet. The manager will review, optionally refine in chat, then confirm.",
      };
    }
    default:
      return { error: `Unknown tool ${name}` };
  }
}

export async function runRoutePlanner(input: PlannerInput, hooks: PlannerHooks): Promise<PlannerResult> {
  const client = anthropic();
  const pace: PaceModel = { timePerDoorSec: input.timePerDoorSec, walkSpeedMps: input.walkSpeedMps };
  const ctx: Ctx = { input, pace, streets: [], homes: [], pastLines: [], preview: null, geoCache: null, summary: "" };

  // Picked-place coordinates skip the (unreliable for bare postal codes) geocode.
  if (input.center && input.bounds) {
    ctx.center = input.center;
    ctx.bounds = clampBounds(input.bounds, 4);
    ctx.displayName = input.area;
  }

  const pairs = Math.max(1, Math.floor(input.marketers.length / 2));
  const sessionTxt = input.sessionHours ? `${input.sessionHours}h session` : "shift-length session";
  const userPrompt = `Plan field routes inside one postal code.

Postal code: ${input.area}
Date: ${input.date}
Session length: ${sessionTxt}. Pace: ${(input.timePerDoorSec / 60).toFixed(1)} min/door, ${(input.walkSpeedMps * 3.6).toFixed(1)} km/h walking.
Avoid streets covered in the last ${input.avoidDays} days.

Marketers (${input.marketers.length}):
${input.marketers.map((m) => `- id=${m.id} | ${m.name} | home: ${m.territory || "n/a"} | shift ${m.start}-${m.end}`).join("\n")}

That's ${pairs} pair(s) → ${pairs} route(s). Pair them up and propose the preview.`;

  const messages: Anthropic.MessageParam[] = [{ role: "user", content: userPrompt }];

  for (let i = 0; i < 16; i++) {
    const resp = await client.messages.create({
      model: MODEL,
      max_tokens: 16000,
      thinking: { type: "adaptive" },
      system: [{ type: "text", text: SYSTEM, cache_control: { type: "ephemeral" } }],
      tools,
      messages,
    });
    messages.push({ role: "assistant", content: resp.content });

    if (resp.stop_reason !== "tool_use") {
      const text = resp.content.filter((b): b is Anthropic.TextBlock => b.type === "text").map((b) => b.text).join("\n").trim();
      if (text) ctx.summary = text;
      break;
    }

    const toolResults: Anthropic.ToolResultBlockParam[] = [];
    for (const block of resp.content) {
      if (block.type !== "tool_use") continue;
      const out = await execute(block.name, block.input, ctx, hooks);
      toolResults.push({
        type: "tool_result",
        tool_use_id: block.id,
        content: JSON.stringify(out),
        is_error: Boolean((out as { error?: string })?.error),
      });
    }
    messages.push({ role: "user", content: toolResults });
  }

  if (ctx.preview) ctx.preview.chat = ctx.summary ? [{ role: "assistant", text: ctx.summary }] : [];
  return { summary: ctx.summary, preview: ctx.preview, geoCache: ctx.geoCache };
}
