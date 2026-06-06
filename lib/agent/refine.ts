import "server-only";
import Anthropic from "@anthropic-ai/sdk";
import { MODEL, anthropic } from "./client";
import { planPreview, type GeoCache, type Steer } from "./preview";
import type { RoutePreview } from "@/lib/types";

// Must match the colours the preview panel paints routes with (PALETTE order).
const COLORS = ["green", "blue", "orange", "purple", "red", "teal", "pink", "lime"];

const SYSTEM = `You are RouteIQ's route refiner. A manager is reviewing a PREVIEW of door-to-door walking routes and wants to adjust it in plain language. Translate their request into structured steering, then write a one-to-two sentence reply describing what you changed.

You do NOT redraw streets yourself - a deterministic planner re-plans from the steering you emit. Always emit the FULL steering that reflects the whole conversation so far (it is re-applied from scratch each time, not stacked on the previous result).

PER-ROUTE vs ALL-ROUTES sizing - this matters a lot:
- The manager may refer to a specific route by its colour ("the green route"), its number ("route 2"), or its crew/streets. Each preview route below is listed with its number and colour.
- When they want to resize ONE route, put it in routeSizes and leave the others alone. routeSizes ONLY changes the routes you list; every other route keeps its current size. Example: "make the green route bigger" with green being route 1 -> routeSizes: [{ "route": 1, "factor": 1.4 }].
- Use sizeFactor ONLY when they mean ALL routes ("make them all bigger", "everything is too long").
- These combine: sizeFactor sets the size for routes you do not list, and routeSizes overrides specific ones. So if earlier you made all routes 1.5x and now they want only the green one even bigger, emit sizeFactor: 1.5 AND routeSizes: [{ "route": <green>, "factor": 2.0 }].
- Factors are relative to the ORIGINAL size, not the last step. Reflect the whole conversation: if a route was already enlarged and they ask again, raise its factor further.

Other levers:
- excludeStreets: street-name fragments to keep OUT of coverage (e.g. "skip Yonge St").
- focusStreets: street-name fragments to pull coverage TOWARD ("cover X instead", "make sure we get X").
- focusDirection: nudge the whole area north/south/east/west/center.

Only set the levers the request implies; leave the rest unset. Match street fragments to the real street names provided. Keep 'reply' short, concrete, and friendly. Name the route you changed (its colour) in the reply.
Write 'reply' in plain text: never use em dashes or en dashes; use commas, periods, parentheses, or a normal hyphen instead.`;

const tool: Anthropic.Tool = {
  name: "refine_plan",
  description: "Emit the full steering for the re-plan plus a short reply to the manager.",
  input_schema: {
    type: "object",
    properties: {
      routeSizes: {
        type: "array",
        description: "Resize specific routes only. Each entry is a 1-based route number and a size factor (>1 bigger, <1 smaller). Routes not listed are unchanged.",
        items: {
          type: "object",
          properties: {
            route: { type: "integer", description: "1-based route number from the list." },
            factor: { type: "number", description: "Size factor for that route, >1 bigger, <1 smaller." },
          },
          required: ["route", "factor"],
        },
      },
      sizeFactor: { type: "number", description: "Scale ALL routes (only when the manager means every route). >1 bigger, <1 smaller." },
      excludeStreets: { type: "array", items: { type: "string" }, description: "Street-name fragments to exclude." },
      focusStreets: { type: "array", items: { type: "string" }, description: "Street-name fragments to pull coverage toward." },
      focusDirection: { type: "string", enum: ["north", "south", "east", "west", "center"] },
      reply: { type: "string", description: "1-2 sentence reply naming the route(s) changed." },
    },
    required: ["reply"],
  },
};

interface RefineArgs {
  routeSizes?: { route: number; factor: number }[];
  sizeFactor?: number;
  excludeStreets?: string[];
  focusStreets?: string[];
  focusDirection?: Steer["focusDirection"];
  reply?: string;
}

export async function refinePreview(
  cache: GeoCache,
  current: RoutePreview,
  message: string,
): Promise<{ preview: RoutePreview; reply: string }> {
  const client = anthropic();

  const streetNames = [...new Set(cache.streets.map((s) => s.name).filter(Boolean))].slice(0, 60);
  const routeLines = current.routes
    .map(
      (r, i) =>
        `${i + 1}. (${COLORS[i % COLORS.length]}) ${r.name} - ${r.doors} doors, ~${r.minutes}m, streets: ${r.topStreets.join(", ")}, crew: ${r.marketerNames.join(" & ")}`,
    )
    .join("\n");
  const history = current.chat
    .slice(-8)
    .map((c) => `${c.role === "user" ? "Manager" : "You"}: ${c.text}`)
    .join("\n");

  const userPrompt = `Area: ${cache.displayName || cache.area}

Current preview (${current.routes.length} route${current.routes.length === 1 ? "" : "s"}), numbered with their map colour:
${routeLines}

Real street names available here: ${streetNames.join(", ")}

${history ? `Conversation so far:\n${history}\n\n` : ""}Manager's new request: "${message}"

Emit the full steering (reflecting the whole conversation) and a short reply.`;

  const resp = await client.messages.create({
    model: MODEL,
    max_tokens: 2000,
    system: [{ type: "text", text: SYSTEM, cache_control: { type: "ephemeral" } }],
    tools: [tool],
    tool_choice: { type: "tool", name: "refine_plan" },
    messages: [{ role: "user", content: userPrompt }],
  });

  const call = resp.content.find((b): b is Anthropic.ToolUseBlock => b.type === "tool_use");
  const args = (call?.input ?? {}) as RefineArgs;
  const reply = args.reply?.trim() || "Updated the preview.";

  // Map 1-based route numbers to a 0-based per-route factor map.
  const routeSizeFactors: Record<number, number> = {};
  for (const rs of args.routeSizes ?? []) {
    const idx = Math.round(rs.route) - 1;
    if (idx >= 0 && idx < current.routes.length && typeof rs.factor === "number" && rs.factor > 0) {
      routeSizeFactors[idx] = rs.factor;
    }
  }

  const steer: Steer = {
    excludeStreets: args.excludeStreets,
    focusStreets: args.focusStreets,
    focusDirection: args.focusDirection,
    sizeFactor: args.sizeFactor,
    routeSizeFactors: Object.keys(routeSizeFactors).length ? routeSizeFactors : undefined,
  };

  const { routes, totalHomes } = planPreview(cache, steer);
  const next: RoutePreview = {
    area: current.area,
    date: current.date,
    totalHomes: routes.length ? totalHomes : current.totalHomes,
    routes: routes.length ? routes : current.routes, // keep prior if a bad steer emptied it
    chat: [...current.chat, { role: "user", text: message }, { role: "assistant", text: reply }],
  };
  return { preview: next, reply };
}
