import "server-only";
import Anthropic from "@anthropic-ai/sdk";
import { MODEL, anthropic, isAnthropicConfigured } from "./client";
import { supabaseAdmin } from "@/lib/supabase/server";

/* ----------------------------------------------------------------------------
   Session grader (Phase 3). After a session ends, this reads the full doorstep
   transcript and grades the rep against THEIR team's playbook - the script flow,
   the grading criteria (opener / discovery / objections / value / close), and the
   approved objection handles. It writes:
     • an overall 0-100 grade onto D2D_Sessions.grade (weighted by the criteria),
     • per-criterion + coaching insights into D2D_AgentInsights (script-adherence,
       objection, coaching, tone) so they surface in the manager's agent panel.
   One forced-tool Claude call - an analysis task, not an agent loop.
---------------------------------------------------------------------------- */

type Criterion = { id: string; label: string; weight: number; description: string };
type Objection = { id: string; trigger: string; category: string; handle: string };

const SYSTEM = `You are RouteIQ's performance coach for a door-to-door sales team. You grade a single rep's shift against THEIR company's playbook, using only the doorstep transcript (the rep is "rep", the homeowner "prospect"; "agent" lines are the rep's own notes / walking gaps - ignore them for grading).

You are given:
- the company's doorstep SCRIPT (the flow reps are coached to run),
- the GRADING CRITERIA (each with an id, label, weight, and what "good" looks like),
- the approved OBJECTION HANDLES (trigger → category → how the rep should respond).

Grade fairly and specifically against THIS playbook - not a generic ideal. Score each criterion 0-100 based on what the transcript actually shows, with a short evidence-based note (quote or paraphrase a real moment). Be honest: reward following the script and the approved handles; dock for skipped discovery, pitching before qualifying, mishandled or ignored objections, and weak/absent closes.

Then surface 3-6 of the most useful COACHING MOMENTS a manager should see - the strongest and the most fixable. For each, pick the right kind:
- "objection": the rep faced an objection - say whether they used the approved handle (set objectionId to the matching objection id) and how it went.
- "script-adherence": followed or skipped a key part of the script (opener, discovery, value, close).
- "coaching": a concrete, actionable improvement for next time.
- "tone": notable rapport, empathy, pushiness, or energy.
Give each moment a 0-100 score for that specific moment. Keep titles <60 chars and details <240 chars, grounded in the transcript. Never invent details.
Write every title and note in plain text: never use em dashes or en dashes; use commas, periods, parentheses, or a normal hyphen instead.`;

const tools: Anthropic.Tool[] = [
  {
    name: "grade_session",
    description: "Record the playbook-based grade for this session.",
    input_schema: {
      type: "object",
      properties: {
        overallGrade: { type: "integer", description: "0-100 overall grade for the shift." },
        headline: { type: "string", description: "One-line manager summary of how the shift went (<160 chars)." },
        criteria: {
          type: "array",
          description: "Score for each grading criterion provided.",
          items: {
            type: "object",
            properties: {
              id: { type: "string", description: "The criterion id from the playbook." },
              label: { type: "string" },
              score: { type: "integer", description: "0-100 for this criterion." },
              note: { type: "string", description: "Evidence-based note (<200 chars)." },
            },
            required: ["id", "score", "note"],
          },
        },
        moments: {
          type: "array",
          description: "3-6 key coaching moments.",
          items: {
            type: "object",
            properties: {
              kind: { type: "string", enum: ["objection", "script-adherence", "coaching", "tone"] },
              title: { type: "string" },
              detail: { type: "string" },
              score: { type: "integer", description: "0-100 for this moment." },
              objectionId: { type: "string", description: "Matching objection id, for kind=objection." },
            },
            required: ["kind", "title", "detail"],
          },
        },
      },
      required: ["overallGrade", "headline", "criteria", "moments"],
    },
  },
];

export function isSessionGraderConfigured(): boolean {
  return isAnthropicConfigured();
}

interface GradeResult {
  overallGrade: number;
  headline: string;
  criteria: { id: string; label?: string; score: number; note: string }[];
  moments: { kind: string; title: string; detail: string; score?: number; objectionId?: string }[];
}

const clamp = (n: number) => Math.max(0, Math.min(100, Math.round(n)));
const INSIGHT_KINDS = new Set(["objection", "script-adherence", "pace", "lead-detected", "coaching", "tone"]);

/** Grade one finished session against its team's playbook. Safe in `after()`. */
export async function gradeSession(sessionId: string): Promise<number | null> {
  if (!isSessionGraderConfigured()) return null;
  const db = supabaseAdmin();

  const { data: session } = await db
    .from("D2D_Sessions")
    .select("id,team_id,marketer_id")
    .eq("id", sessionId)
    .maybeSingle();
  if (!session) return null;

  // The team's playbook - what we grade against.
  let pbQuery = db.from("D2D_Playbooks").select("script,objections,grading_criteria");
  pbQuery = session.team_id ? pbQuery.eq("team_id", session.team_id) : pbQuery;
  const { data: playbook } = await pbQuery.limit(1).maybeSingle();
  const script = (playbook?.script as string) ?? "";
  const criteria = ((playbook?.grading_criteria as Criterion[]) ?? []).filter((c) => c?.id);
  const objections = ((playbook?.objections as Objection[]) ?? []).filter((o) => o?.id);
  if (!script && !criteria.length) return null; // nothing to grade against

  // Full conversation (final lines only, in order).
  const { data: lineRows } = await db
    .from("D2D_TranscriptLines")
    .select("speaker,text,seq")
    .eq("session_id", sessionId)
    .eq("is_final", true)
    .order("seq", { ascending: true })
    .limit(800);
  const convo = (lineRows ?? [])
    .map((r) => `${r.speaker}: ${r.text}`)
    .join("\n")
    .slice(0, 24000);
  if (!convo.trim()) return null;

  const criteriaTxt = criteria.length
    ? criteria.map((c) => `- [${c.id}] ${c.label} (weight ${c.weight}): ${c.description}`).join("\n")
    : "- [overall] Overall doorstep effectiveness (weight 100): opener, discovery, objection handling, value, close.";
  const objectionsTxt = objections.length
    ? objections.map((o) => `- [${o.id}] (${o.category}) "${o.trigger}" → ${o.handle}`).join("\n")
    : "(none provided)";

  const userPrompt = `COMPANY SCRIPT:
${script || "(no script provided - grade against the criteria)"}

GRADING CRITERIA:
${criteriaTxt}

APPROVED OBJECTION HANDLES:
${objectionsTxt}

SHIFT TRANSCRIPT (all doors this session):
${convo}

Grade this shift against the playbook via grade_session.`;

  let result: GradeResult | null = null;
  try {
    const client = anthropic();
    const resp = await client.messages.create({
      model: MODEL,
      max_tokens: 4000,
      system: [{ type: "text", text: SYSTEM, cache_control: { type: "ephemeral" } }],
      tools,
      tool_choice: { type: "tool", name: "grade_session" },
      messages: [{ role: "user", content: userPrompt }],
    });
    const block = resp.content.find((b) => b.type === "tool_use");
    if (block && block.type === "tool_use") result = block.input as GradeResult;
  } catch {
    return null; // never let grading break the session lifecycle
  }
  if (!result) return null;

  // Prefer a principled weighted grade from the per-criterion scores; fall back
  // to the model's overall if criteria weights are missing.
  const weightById = new Map(criteria.map((c) => [c.id, c.weight] as const));
  let weighted = 0;
  let wsum = 0;
  for (const c of result.criteria ?? []) {
    const w = weightById.get(c.id) ?? 0;
    if (w > 0 && typeof c.score === "number") {
      weighted += clamp(c.score) * w;
      wsum += w;
    }
  }
  const grade = wsum > 0 ? clamp(weighted / wsum) : clamp(result.overallGrade ?? 0);

  // Persist the grade on the session.
  await db.from("D2D_Sessions").update({ grade }).eq("id", sessionId);

  // Build the insight rows: a headline summary, each criterion, then the moments.
  const objectionIds = new Set(objections.map((o) => o.id));
  const insightRows: Record<string, unknown>[] = [];

  insightRows.push({
    session_id: sessionId,
    kind: "coaching",
    title: `Shift graded - ${grade}/100`,
    detail: result.headline?.slice(0, 240) ?? "",
    score: grade,
  });

  for (const c of result.criteria ?? []) {
    const label = c.label ?? criteria.find((x) => x.id === c.id)?.label ?? c.id;
    insightRows.push({
      session_id: sessionId,
      kind: "script-adherence",
      title: `${label}: ${clamp(c.score)}/100`,
      detail: (c.note ?? "").slice(0, 240),
      score: clamp(c.score),
    });
  }

  for (const m of result.moments ?? []) {
    const kind = INSIGHT_KINDS.has(m.kind) ? m.kind : "coaching";
    insightRows.push({
      session_id: sessionId,
      kind,
      title: (m.title ?? "Coaching note").slice(0, 80),
      detail: (m.detail ?? "").slice(0, 240),
      score: typeof m.score === "number" ? clamp(m.score) : null,
      objection_id: m.objectionId && objectionIds.has(m.objectionId) ? m.objectionId : null,
    });
  }

  if (insightRows.length) await db.from("D2D_AgentInsights").insert(insightRows);
  return grade;
}
