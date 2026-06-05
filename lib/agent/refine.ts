import "server-only";
import Anthropic from "@anthropic-ai/sdk";
import { planPreview, type GeoCache, type Steer } from "./preview";
import type { RoutePreview } from "@/lib/types";

const MODEL = "claude-opus-4-8";

const SYSTEM = `You are RouteIQ's route refiner. A manager is reviewing a PREVIEW of door-to-door walking routes and wants to adjust it in plain language. Translate their request into structured steering, then write a one-to-two sentence reply describing what you changed.

You do NOT redraw streets yourself — a deterministic planner re-plans from the steering you emit. Always emit the FULL steering that reflects the whole conversation so far (it is re-applied from scratch each time, not stacked on the previous result).

Steering levers (call refine_plan exactly once):
- excludeStreets: street-name fragments to keep OUT of coverage (e.g. manager says "skip Yonge St").
- focusStreets: street-name fragments to pull coverage TOWARD — use when they say "cover X instead" or "make sure we get X".
- focusDirection: nudge the whole area north/south/east/west/center (e.g. "shift it east", "focus closer to downtown").
- sizeFactor: scale every route's size. >1 = bigger (more doors), <1 = smaller. "make them bigger" ≈ 1.3, "too long, trim them" ≈ 0.75.

Only set the levers the request implies; leave the rest unset. Match street fragments to the real street names provided. Keep 'reply' short, concrete, and friendly.`;

const tool: Anthropic.Tool = {
  name: "refine_plan",
  description: "Emit the full steering for the re-plan plus a short reply to the manager.",
  input_schema: {
    type: "object",
    properties: {
      excludeStreets: { type: "array", items: { type: "string" }, description: "Street-name fragments to exclude." },
      focusStreets: { type: "array", items: { type: "string" }, description: "Street-name fragments to pull coverage toward." },
      focusDirection: { type: "string", enum: ["north", "south", "east", "west", "center"] },
      sizeFactor: { type: "number", description: "Scale routes — >1 bigger, <1 smaller." },
      reply: { type: "string", description: "1-2 sentence reply to the manager about what changed." },
    },
    required: ["reply"],
  },
};

export async function refinePreview(
  cache: GeoCache,
  current: RoutePreview,
  message: string,
): Promise<{ preview: RoutePreview; reply: string }> {
  const client = new Anthropic();

  const streetNames = [...new Set(cache.streets.map((s) => s.name).filter(Boolean))].slice(0, 60);
  const routeLines = current.routes
    .map((r, i) => `${i + 1}. ${r.name} — ${r.doors} doors, ~${r.minutes}m, streets: ${r.topStreets.join(", ")}, crew: ${r.marketerNames.join(" & ")}`)
    .join("\n");
  const history = current.chat
    .slice(-8)
    .map((c) => `${c.role === "user" ? "Manager" : "You"}: ${c.text}`)
    .join("\n");

  const userPrompt = `Area: ${cache.displayName || cache.area}

Current preview (${current.routes.length} route${current.routes.length === 1 ? "" : "s"}):
${routeLines}

Real street names available here: ${streetNames.join(", ")}

${history ? `Conversation so far:\n${history}\n\n` : ""}Manager's new request: "${message}"

Emit the full steering (reflecting the whole conversation) and a short reply.`;

  const resp = await client.messages.create({
    model: MODEL,
    max_tokens: 2000,
    thinking: { type: "adaptive" },
    system: [{ type: "text", text: SYSTEM, cache_control: { type: "ephemeral" } }],
    tools: [tool],
    tool_choice: { type: "tool", name: "refine_plan" },
    messages: [{ role: "user", content: userPrompt }],
  });

  const call = resp.content.find((b): b is Anthropic.ToolUseBlock => b.type === "tool_use");
  const args = (call?.input ?? {}) as Steer & { reply?: string };
  const reply = args.reply?.trim() || "Updated the preview.";
  const steer: Steer = {
    excludeStreets: args.excludeStreets,
    focusStreets: args.focusStreets,
    focusDirection: args.focusDirection,
    sizeFactor: args.sizeFactor,
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
