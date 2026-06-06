import "server-only";
import Anthropic from "@anthropic-ai/sdk";
import { MODEL, anthropic, isAnthropicConfigured } from "./client";
import { supabaseAdmin } from "@/lib/supabase/server";
import { reverseGeocode } from "@/lib/geo/geocode";

/* ----------------------------------------------------------------------------
   Lead spotter (Phase 2). Scans a window of a door-to-door sales transcript and
   extracts genuinely-interested prospects as structured leads, then writes them
   to the CRM (D2D_Leads, source=auto-detected) and emits a lead-detected insight.
   Single forced-tool Claude call per scan - an extraction task, not an agent.
---------------------------------------------------------------------------- */

const SYSTEM = `You are RouteIQ's lead spotter for a door-to-door home-services company (any trade - e.g. window cleaning, roofing, pest control).

You read a transcript of a rep's doorstep conversations (the rep is labelled "rep",
the homeowner "prospect") and identify GENUINELY INTERESTED prospects worth adding to
the CRM as leads.

HARD REQUIREMENT - a prospect is ONLY a lead if the transcript contains BOTH:
  1. their ACTUAL NAME, said by them (a real first name at minimum, e.g. "Janet" or
     "Janet Walsh"), AND
  2. a PHONE NUMBER they gave.
If either is missing, DO NOT report them, no matter how interested they sound. A booking
with no phone number is not a lead. A phone number with no name is not a lead.

The name field MUST be the real name they stated. NEVER output a placeholder or
descriptor such as "the prospect", "Prospect", "Homeowner", "Resident", "Owner",
"Customer", "the man/woman at 211", or a street description. If they never actually said
their name, they are NOT a lead - leave them out entirely.

On top of that minimum, the prospect should show real interest: agreeing to a quote /
appointment / service, asking for a callback, or clear specific interest.

What is NOT a lead: anyone without both a name and phone number, flat refusals,
"not interested", "no thanks", nobody home, small talk with no buying signal, or the rep
talking to themselves between doors.

For each qualifying prospect, extract:
- name: the prospect's stated name (required).
- phone: the phone number they gave (required).
- address / email: only if explicitly stated in the transcript; otherwise omit.
- summary: one or two sentences a manager can scan - who they are and why they're a lead.
- score: 0-100 confidence/quality. 80+ booked an appointment or gave contact info; 60-79 clear
  interest / callback; 50-59 mild curiosity. Do NOT report anything you'd score below 50.
- transcriptSnippet: the single most telling quote (verbatim, <160 chars) showing the interest.

Be conservative - precision matters more than recall. If no one qualifies, return an empty list.
Never invent contact details. Never re-report a prospect already in the "already captured" list.
Write all text (summaries especially) in plain prose: never use em dashes or en dashes; use commas, periods, parentheses, or a normal hyphen instead.`;

const tools: Anthropic.Tool[] = [
  {
    name: "record_leads",
    description: "Record the interested prospects (leads) found in the transcript window.",
    input_schema: {
      type: "object",
      properties: {
        leads: {
          type: "array",
          description: "Leads found. Empty if no prospect showed genuine interest.",
          items: {
            type: "object",
            properties: {
              name: { type: "string", description: "The prospect's real stated name (required). Never a placeholder like 'the prospect' or 'Homeowner'." },
              phone: { type: "string", description: "Phone number the prospect gave (required)." },
              address: { type: "string", description: "Street address, only if stated." },
              email: { type: "string", description: "Email, only if stated." },
              summary: { type: "string", description: "1-2 sentence manager-facing summary." },
              score: { type: "integer", description: "0-100 confidence/quality. Omit if <50." },
              transcriptSnippet: { type: "string", description: "Most telling verbatim quote." },
            },
            required: ["name", "phone", "summary", "score", "transcriptSnippet"],
          },
        },
      },
      required: ["leads"],
    },
  },
];

export interface SpottedLead {
  name: string;
  address?: string;
  phone?: string;
  email?: string;
  summary: string;
  score: number;
  transcriptSnippet: string;
}

export function isLeadSpotterConfigured(): boolean {
  return isAnthropicConfigured();
}

/** One Claude call: transcript window → structured leads. */
export async function spotLeads(opts: {
  transcript: { speaker: string; text: string }[];
  existingLeadNames?: string[];
}): Promise<SpottedLead[]> {
  if (!isLeadSpotterConfigured() || !opts.transcript.length) return [];

  const convo = opts.transcript.map((t) => `${t.speaker}: ${t.text}`).join("\n");
  const dedupe = opts.existingLeadNames?.length
    ? `\n\nAlready captured (do NOT report these again):\n- ${opts.existingLeadNames.join("\n- ")}`
    : "";
  const userPrompt = `Transcript window:\n\n${convo}${dedupe}\n\nReturn any NEW qualifying leads via record_leads.`;

  const client = anthropic();
  const resp = await client.messages.create({
    model: MODEL,
    max_tokens: 2048,
    system: [{ type: "text", text: SYSTEM, cache_control: { type: "ephemeral" } }],
    tools,
    tool_choice: { type: "tool", name: "record_leads" },
    messages: [{ role: "user", content: userPrompt }],
  });

  const block = resp.content.find((b) => b.type === "tool_use");
  if (!block || block.type !== "tool_use") return [];
  const leads = (block.input as { leads?: SpottedLead[] }).leads ?? [];
  // Enforce the minimum: a lead must have a REAL name and a phone number.
  const hasPhone = (s?: string) => Boolean(s && /\d/.test(s) && s.replace(/\D/g, "").length >= 7);
  return leads.filter(
    (l) => isRealName(l?.name) && hasPhone(l.phone) && typeof l.score === "number" && l.score >= 50,
  );
}

// Reject placeholder/descriptor names so a lead always has an actual person's name.
const GENERIC_NAME =
  /\b(prospect|home\s?owner|resident|customer|client|tenant|occupant|caller|unknown|someone|some\s?one|n\/?a|the\s+(man|woman|lady|guy|person|owner|homeowner|resident))\b/i;
function isRealName(name?: string): boolean {
  const n = (name ?? "").trim();
  if (n.length < 2) return false;
  if (!/[a-z]/i.test(n)) return false; // must contain letters
  if (GENERIC_NAME.test(n)) return false; // generic descriptor
  if (/\bon\s+[a-z].*\b(st|street|ave|avenue|rd|road|dr|drive|blvd|lane|ln|way|cres|crescent|court|ct)\b/i.test(n))
    return false; // "Homeowner on Maple St" style
  return true;
}

/** Orchestration: load the session + a recent transcript window, dedup against
 *  leads already captured for this session, spot new leads, and persist them to
 *  the CRM + emit a lead-detected insight. Safe to call from `after()`. Returns
 *  the number of new leads created. */
export async function detectAndStoreLeads(
  sessionId: string,
  opts: { maxLines?: number } = {},
): Promise<number> {
  if (!isLeadSpotterConfigured()) return 0;
  const maxLines = opts.maxLines ?? 120;
  const db = supabaseAdmin();

  const { data: session } = await db
    .from("D2D_Sessions")
    .select("id,team_id,marketer_id,territory,lat,lng")
    .eq("id", sessionId)
    .maybeSingle();
  if (!session) return 0;

  // Recent transcript window (final lines only).
  const { data: lineRows } = await db
    .from("D2D_TranscriptLines")
    .select("speaker,text,seq")
    .eq("session_id", sessionId)
    .eq("is_final", true)
    .order("seq", { ascending: false })
    .limit(maxLines);
  const transcript = (lineRows ?? [])
    .reverse()
    .map((r) => ({ speaker: r.speaker as string, text: r.text as string }));
  if (!transcript.length) return 0;

  // Dedup against leads already captured in this session.
  const { data: existing } = await db
    .from("D2D_Leads")
    .select("name")
    .eq("session_id", sessionId);
  const existingNames = (existing ?? []).map((l) => (l.name as string) ?? "").filter(Boolean);
  const existingLower = new Set(existingNames.map((n) => n.toLowerCase()));

  let spotted: SpottedLead[];
  try {
    spotted = await spotLeads({ transcript, existingLeadNames: existingNames });
  } catch {
    return 0; // never let detection break the session lifecycle
  }

  // Dedup within this batch (same person returned twice) by phone-digits-or-name,
  // and against leads already captured this session.
  const seen = new Set<string>();
  const keyOf = (l: SpottedLead) =>
    (l.phone ?? "").replace(/\D/g, "") || l.name.trim().toLowerCase();
  const fresh = spotted.filter((l) => {
    if (existingLower.has(l.name.toLowerCase())) return false;
    const k = keyOf(l);
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
  if (!fresh.length) return 0;

  // Door pins (with their GPS + conversation excerpt) let us place each lead at
  // the exact home it was collected at - match by the lead's verbatim snippet.
  const { data: doorRows } = await db
    .from("D2D_DoorEvents")
    .select("lat,lng,transcript_excerpt")
    .eq("session_id", sessionId);
  const doors = doorRows ?? [];

  const locFor = (lead: SpottedLead): { lat: number; lng: number } | null => {
    const snip = lead.transcriptSnippet.trim().toLowerCase().slice(0, 40);
    if (snip) {
      const door = doors.find(
        (d) =>
          typeof d.lat === "number" &&
          typeof d.lng === "number" &&
          (d.transcript_excerpt as string | null)?.toLowerCase().includes(snip),
      );
      if (door) return { lat: door.lat as number, lng: door.lng as number };
    }
    if (typeof session.lat === "number" && typeof session.lng === "number") {
      return { lat: session.lat as number, lng: session.lng as number };
    }
    return null;
  };

  const inserted: SpottedLead[] = [];
  for (const l of fresh) {
    const loc = locFor(l);
    // Prefer the GPS-derived address; fall back to anything stated in the convo.
    const address = (loc ? await reverseGeocode(loc.lat, loc.lng) : null) ?? l.address ?? null;
    const { error: insErr } = await db.from("D2D_Leads").insert({
      team_id: session.team_id ?? null,
      marketer_id: session.marketer_id ?? null,
      session_id: sessionId,
      name: l.name,
      address,
      lat: loc?.lat ?? null,
      lng: loc?.lng ?? null,
      phone: l.phone ?? null,
      email: l.email ?? null,
      status: "new",
      score: Math.max(0, Math.min(100, Math.round(l.score))),
      territory: session.territory ?? null,
      source: "auto-detected",
      summary: l.summary,
      transcript_snippet: l.transcriptSnippet,
    });
    // 23505 = unique violation: a concurrent pass already captured this lead. Skip.
    if (insErr) continue;
    inserted.push(l);
  }
  if (!inserted.length) return 0;

  // Mirror into the live agent panel + bump the session's lead counter.
  await db.from("D2D_AgentInsights").insert(
    inserted.map((l) => ({
      session_id: sessionId,
      kind: "lead-detected",
      title: `Lead: ${l.name}`,
      detail: l.summary,
      score: Math.max(0, Math.min(100, Math.round(l.score))),
    })),
  );
  const { data: sRow } = await db
    .from("D2D_Sessions")
    .select("leads")
    .eq("id", sessionId)
    .maybeSingle();
  await db
    .from("D2D_Sessions")
    .update({ leads: ((sRow?.leads as number) ?? 0) + inserted.length })
    .eq("id", sessionId);

  return inserted.length;
}
