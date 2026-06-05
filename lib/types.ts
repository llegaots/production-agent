/* ----------------------------------------------------------------------------
   Domain model for RouteIQ. These shapes are mirrored 1:1 by the planned
   Supabase tables so the mock data-access layer can be swapped without churn.
---------------------------------------------------------------------------- */

export type LatLng = { lat: number; lng: number };

export type RepStatus = "live" | "break" | "offline";

export interface Rep {
  id: string;
  name: string;
  avatarTint: AccentTint;
  status: RepStatus;
  territory: string;
  email?: string;
  phone?: string;
  /** rolling letter-grade score 0-100 */
  grade: number;
  doorsToday: number;
  conversationsToday: number;
  leadsToday: number;
  /** doors per hour */
  pace: number;
  /** % of doors that opened */
  answerRate: number;
  /** % of conversations that became leads */
  conversionRate: number;
  hoursToday: number;
  trend: number[]; // last ~12 sessions grade trend
  joinedAt: string;
}

export type SessionStatus = "live" | "completed" | "paused";

export interface Session {
  id: string;
  repId: string;
  repName: string;
  status: SessionStatus;
  startedAt: string;
  endedAt?: string;
  territory: string;
  routeId: string;
  doors: number;
  conversations: number;
  leads: number;
  noAnswers: number;
  grade: number;
  /** the rep's live position */
  position: LatLng;
  /** breadcrumb trail of visited doors */
  trail: DoorPing[];
  /** the rep's walked GPS trail this session (persisted, downsampled) */
  trailPath?: LatLng[];
  /** the planned route geometry, for the grey baseline on cards */
  routePath?: LatLng[];
}

export type DoorOutcome = "answered" | "no-answer" | "callback" | "not-interested" | "lead";

export interface DoorPing {
  id: string;
  at: string;
  position: LatLng;
  outcome: DoorOutcome;
  address?: string;
  /** one-line AI summary of what happened at this door (shown on map hover) */
  note?: string;
}

export type Speaker = "rep" | "prospect" | "agent";

export interface TranscriptLine {
  id: string;
  at: string;
  speaker: Speaker;
  text: string;
  /** sentiment -1..1 */
  sentiment?: number;
}

export type InsightKind =
  | "objection"
  | "script-adherence"
  | "pace"
  | "lead-detected"
  | "coaching"
  | "tone";

export interface AgentInsight {
  id: string;
  at: string;
  kind: InsightKind;
  title: string;
  detail: string;
  /** 0-100 quality score for the moment */
  score?: number;
  objectionId?: string;
}

export type LeadStatus = "new" | "qualified" | "callback" | "appointment" | "won" | "lost";

export interface Lead {
  id: string;
  name: string;
  address: string;
  position: LatLng;
  phone?: string;
  email?: string;
  status: LeadStatus;
  /** AI lead score 0-100 */
  score: number;
  repId: string;
  repName: string;
  territory: string;
  capturedAt: string;
  source: "auto-detected" | "manual";
  summary: string;
  transcriptSnippet: string;
  tags: string[];
}

export type RouteStatus = "active" | "scheduled" | "completed";

export interface RoutePartner {
  id: string;
  name: string;
  tint: AccentTint;
}

export interface Route {
  id: string;
  name: string;
  territory: string;
  status: RouteStatus;
  assignedRepId?: string;
  assignedRepName?: string;
  /** the pair (or trio) walking this route together */
  assignedMarketers?: RoutePartner[];
  center: LatLng;
  path: LatLng[];
  doorsPlanned: number;
  doorsHit: number;
  answered: number;
  leads: number;
  coverage: number; // 0-100
  createdAt: string;
  scheduledFor?: string;
  areaInput?: string;
  generationId?: string;
}

export interface Team {
  id: string;
  name: string;
}

export type GenerationStatus =
  | "queued"
  | "running"
  | "preview"
  | "confirmed"
  | "done"
  | "error";

/** One proposed route in a generation preview (before it's committed). */
export interface PreviewRoute {
  tempId: string;
  name: string;
  territory: string;
  topStreets: string[];
  path: LatLng[];
  center: LatLng;
  meet: LatLng;
  doors: number;
  minutes: number;
  marketerIds: string[];
  marketerNames: string[];
}

export interface PreviewChatTurn {
  role: "user" | "assistant";
  text: string;
}

/** The reviewable, refine-able proposal stored on a generation row. */
export interface RoutePreview {
  area: string;
  date: string;
  totalHomes: number;
  routes: PreviewRoute[];
  chat: PreviewChatTurn[];
}

export interface RouteGeneration {
  id: string;
  areaInput: string;
  status: GenerationStatus;
  /** human-readable current stage, e.g. "Fetching streets" */
  stage: string;
  /** 0-100 */
  progress: number;
  agentSummary?: string;
  error?: string;
  createdAt: string;
  completedAt?: string;
  preview?: RoutePreview | null;
}

export interface Objection {
  id: string;
  trigger: string;
  category: "price" | "timing" | "trust" | "need" | "authority" | "stall";
  handle: string;
  /** how often agents see this in the field */
  frequency: number;
  /** average handle success 0-100 */
  successRate: number;
}

export interface Playbook {
  scriptTitle: string;
  script: string;
  objections: Objection[];
  gradingCriteria: { id: string; label: string; weight: number; description: string }[];
}

export type AccentTint = "emerald" | "sky" | "violet" | "amber" | "rose";

export interface KpiStat {
  id: string;
  label: string;
  value: number;
  suffix?: string;
  hint: string;
  delta?: number;
  tint: AccentTint;
  icon: string;
}

export interface TerritoryRow {
  id: string;
  name: string;
  territory: string;
  reps: number;
  doors: number;
  answerRate: number;
  leads: number;
  status: RouteStatus;
}

export interface ActivityItem {
  id: string;
  at: string;
  repName: string;
  tint: AccentTint;
  kind: "lead" | "appointment" | "objection" | "milestone";
  text: string;
}

export interface DashboardData {
  kpis: KpiStat[];
  doorsSeries: { label: string; value: number }[];
  territoryPerformance: TerritoryRow[];
  liveActivity: ActivityItem[];
}

export type ShiftStatus = "scheduled" | "active" | "completed";

export interface Shift {
  id: string;
  repId: string;
  repName: string;
  tint: AccentTint;
  routeId?: string;
  territory: string;
  /** ISO date, YYYY-MM-DD */
  date: string;
  /** 24h HH:mm */
  start: string;
  end: string;
  status: ShiftStatus;
  notes?: string;
}
