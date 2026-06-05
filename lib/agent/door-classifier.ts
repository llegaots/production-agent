import "server-only";
import Anthropic from "@anthropic-ai/sdk";
import type { DoorOutcome } from "@/lib/types";

/* ----------------------------------------------------------------------------
   Classifies a single door visit from the conversation that happened there.
   No prospect speech in the window → "no-answer" (no AI call). Otherwise a
   single forced-tool Claude call returns the outcome + a one-line note.
---------------------------------------------------------------------------- */

const MODEL = "claude-opus-4-8";

const SYSTEM = `You classify the outcome of a single door knock for a door-to-door sales rep (any home-service trade - e.g. window cleaning, roofing, pest control), based on the conversation at that door (the rep is "rep", the homeowner "prospect").

Pick exactly one outcome:
- "lead": prospect booked an appointment/quote/service, asked for a quote/callback with clear intent, or gave contact info in a buying context.
- "callback": prospect was open but wants to be contacted later / not ready now.
- "answered": prospect talked but with no clear interest yet (neutral conversation).
- "not-interested": prospect declined, said no, or shut it down.

Also write a one-line note (<140 chars) a manager can scan: what happened and any next step.
Base it only on the transcript. Do not invent details.
Write the note in plain text: never use em dashes or en dashes; use commas, periods, parentheses, or a normal hyphen instead.`;

const tools: Anthropic.Tool[] = [
  {
    name: "classify_door",
    description: "Record the outcome of this door visit.",
    input_schema: {
      type: "object",
      properties: {
        outcome: {
          type: "string",
          enum: ["lead", "callback", "answered", "not-interested"],
        },
        note: { type: "string", description: "One-line manager-facing summary (<140 chars)." },
      },
      required: ["outcome", "note"],
    },
  },
];

export interface DoorClassification {
  outcome: DoorOutcome;
  note: string;
}

export function isDoorClassifierConfigured(): boolean {
  return Boolean(process.env.ANTHROPIC_API_KEY);
}

export async function classifyDoor(
  transcript: { speaker: string; text: string }[],
): Promise<DoorClassification> {
  const hadProspect = transcript.some((t) => t.speaker === "prospect" && t.text.trim());
  if (!hadProspect) {
    return { outcome: "no-answer", note: "No one answered the door." };
  }
  if (!isDoorClassifierConfigured()) {
    // Someone spoke but no AI available - record a neutral answered outcome.
    return { outcome: "answered", note: "Conversation at the door." };
  }

  const convo = transcript.map((t) => `${t.speaker}: ${t.text}`).join("\n");
  try {
    const client = new Anthropic();
    const resp = await client.messages.create({
      model: MODEL,
      max_tokens: 512,
      system: [{ type: "text", text: SYSTEM, cache_control: { type: "ephemeral" } }],
      tools,
      tool_choice: { type: "tool", name: "classify_door" },
      messages: [{ role: "user", content: `Door conversation:\n\n${convo}\n\nClassify it.` }],
    });
    const block = resp.content.find((b) => b.type === "tool_use");
    if (block && block.type === "tool_use") {
      const out = block.input as { outcome?: DoorOutcome; note?: string };
      if (out.outcome) return { outcome: out.outcome, note: out.note ?? "" };
    }
  } catch {
    // fall through to neutral default
  }
  return { outcome: "answered", note: "Conversation at the door." };
}
