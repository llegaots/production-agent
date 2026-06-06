/* ----------------------------------------------------------------------------
   Data-access seam. Reads come from Supabase (D2D_* tables). When Supabase
   isn't configured, every method degrades to empty so the app still renders.
   Tables that don't exist yet (sessions/leads/playbook/dashboard) stay empty.
---------------------------------------------------------------------------- */
import { supabaseRead } from "@/lib/supabase/server";
import type {
  Rep,
  Route,
  Lead,
  Session,
  Playbook,
  TranscriptLine,
  AgentInsight,
  DoorPing,
  DoorOutcome,
  Shift,
  DashboardData,
  Team,
  RouteGeneration,
  AccentTint,
  LatLng,
  RoutePartner,
  Speaker,
} from "@/lib/types";

const emptyDashboard: DashboardData = {
  kpis: [],
  doorsSeries: [],
  territoryPerformance: [],
  liveActivity: [],
};

const DEFAULT_CENTER: LatLng = { lat: 43.6532, lng: -79.3832 };

const tint = (v: unknown): AccentTint =>
  (["emerald", "sky", "violet", "amber", "rose"].includes(v as string) ? v : "emerald") as AccentTint;

const centerOf = (path: LatLng[]): LatLng =>
  path.length ? path[Math.floor(path.length / 2)] : DEFAULT_CENTER;

/** lat/lng off a row, defaulting to the map's home center when absent. */
const posOf = (r: Record<string, unknown>): LatLng => ({
  lat: (r.lat as number) ?? DEFAULT_CENTER.lat,
  lng: (r.lng as number) ?? DEFAULT_CENTER.lng,
});

function mapLead(
  r: Record<string, unknown>,
  opts: { repName?: string; territory?: string; defaultSource?: Lead["source"] } = {},
): Lead {
  return {
    id: r.id as string,
    name: (r.name as string) ?? "New lead",
    address: (r.address as string) ?? "",
    position: posOf(r),
    phone: (r.phone as string) ?? undefined,
    email: (r.email as string) ?? undefined,
    status: (r.status as Lead["status"]) ?? "new",
    score: (r.score as number) ?? 50,
    repId: (r.marketer_id as string) ?? "",
    repName: opts.repName ?? "",
    territory: (r.territory as string) ?? opts.territory ?? "",
    capturedAt: (r.captured_at as string) ?? (r.created_at as string),
    source: (r.source as Lead["source"]) ?? opts.defaultSource ?? "manual",
    summary: (r.summary as string) ?? "",
    transcriptSnippet: (r.transcript_snippet as string) ?? "",
    tags: (r.tags as string[]) ?? [],
  };
}

const mapTranscriptLine = (r: Record<string, unknown>): TranscriptLine => ({
  id: r.id as string,
  at: (r.at as string) ?? (r.created_at as string),
  speaker: (r.speaker as Speaker) ?? "prospect",
  text: (r.text as string) ?? "",
  sentiment: typeof r.sentiment === "number" ? (r.sentiment as number) : undefined,
});

const mapDoor = (r: Record<string, unknown>): DoorPing => ({
  id: r.id as string,
  at: (r.at as string) ?? (r.created_at as string),
  position: posOf(r),
  outcome: (r.outcome as DoorOutcome) ?? "no-answer",
  address: (r.address as string) ?? undefined,
  note: (r.note as string) ?? undefined,
});

function mapRep(m: Record<string, unknown>): Rep {
  return {
    id: m.id as string,
    name: m.name as string,
    avatarTint: tint(m.avatar_tint),
    status: (m.status as Rep["status"]) ?? "offline",
    territory: (m.home_territory as string) ?? "",
    email: (m.email as string) ?? undefined,
    phone: (m.phone as string) ?? undefined,
    grade: 0,
    doorsToday: 0,
    conversationsToday: 0,
    leadsToday: 0,
    pace: 0,
    answerRate: 0,
    conversionRate: 0,
    hoursToday: 0,
    trend: [],
    joinedAt: (m.joined_at as string) ?? new Date().toISOString(),
  };
}

function mapSession(s: Record<string, unknown>, repName: string, routePath?: LatLng[]): Session {
  return {
    id: s.id as string,
    repId: (s.marketer_id as string) ?? "",
    repName,
    status: (s.status as Session["status"]) ?? "completed",
    startedAt: (s.started_at as string) ?? (s.created_at as string),
    endedAt: (s.ended_at as string) ?? undefined,
    territory: (s.territory as string) ?? "",
    routeId: (s.route_id as string) ?? "",
    doors: (s.doors as number) ?? 0,
    conversations: (s.conversations as number) ?? 0,
    leads: (s.leads as number) ?? 0,
    noAnswers: (s.no_answers as number) ?? 0,
    grade: (s.grade as number) ?? 0,
    position: posOf(s),
    trail: [],
    trailPath: Array.isArray(s.trail_path) ? (s.trail_path as LatLng[]) : [],
    routePath,
  };
}

/** Loads sessions for a set of rows, resolving rep names and planned-route
 *  geometry (for the grey baseline on cards) in batch queries. */
async function hydrateSessions(
  db: NonNullable<ReturnType<typeof supabaseRead>>,
  rows: Record<string, unknown>[],
): Promise<Session[]> {
  if (!rows.length) return [];
  const marketerIds = [...new Set(rows.map((s) => s.marketer_id).filter(Boolean))] as string[];
  const routeIds = [...new Set(rows.map((s) => s.route_id).filter(Boolean))] as string[];
  const [{ data: marketers }, { data: routes }] = await Promise.all([
    marketerIds.length
      ? db.from("D2D_Marketers").select("id,name").in("id", marketerIds)
      : Promise.resolve({ data: [] as Record<string, unknown>[] }),
    routeIds.length
      ? db.from("D2D_Routes").select("id,path").in("id", routeIds)
      : Promise.resolve({ data: [] as Record<string, unknown>[] }),
  ]);
  const nameById = new Map<string, string>();
  (marketers ?? []).forEach((m) => nameById.set(m.id as string, m.name as string));
  const pathById = new Map<string, LatLng[]>();
  (routes ?? []).forEach((r) => pathById.set(r.id as string, (r.path as LatLng[]) ?? []));
  return rows.map((s) =>
    mapSession(
      s,
      nameById.get(s.marketer_id as string) ?? "Unassigned",
      pathById.get(s.route_id as string),
    ),
  );
}

export const data = {
  getTeam: async (): Promise<Team | null> => {
    const db = supabaseRead();
    if (!db) return null;
    const { data: rows } = await db.from("D2D_Teams").select("id,name").limit(1);
    const t = rows?.[0];
    return t ? { id: t.id as string, name: t.name as string } : null;
  },

  getReps: async (): Promise<Rep[]> => {
    const db = supabaseRead();
    if (!db) return [];
    const { data: rows } = await db
      .from("D2D_Marketers")
      .select("*")
      .order("joined_at", { ascending: true });
    return (rows ?? []).map(mapRep);
  },

  getRep: async (id: string): Promise<Rep | null> => {
    const db = supabaseRead();
    if (!db) return null;
    const { data: row } = await db.from("D2D_Marketers").select("*").eq("id", id).maybeSingle();
    return row ? mapRep(row) : null;
  },

  getRoutes: async (): Promise<Route[]> => {
    const db = supabaseRead();
    if (!db) return [];
    const { data: rows } = await db
      .from("D2D_Routes")
      .select("*")
      .order("created_at", { ascending: false });
    if (!rows?.length) return [];

    const routeIds = rows.map((r) => r.id as string);
    const { data: assigns } = await db
      .from("D2D_RouteAssignments")
      .select("route_id,marketer_id")
      .in("route_id", routeIds);
    const marketerIds = [...new Set((assigns ?? []).map((a) => a.marketer_id as string))];
    const { data: marketers } = marketerIds.length
      ? await db.from("D2D_Marketers").select("id,name,avatar_tint").in("id", marketerIds)
      : { data: [] as Record<string, unknown>[] };

    const mById = new Map<string, RoutePartner>();
    (marketers ?? []).forEach((m) =>
      mById.set(m.id as string, { id: m.id as string, name: m.name as string, tint: tint(m.avatar_tint) }),
    );
    const partnersByRoute = new Map<string, RoutePartner[]>();
    (assigns ?? []).forEach((a) => {
      const p = mById.get(a.marketer_id as string);
      if (!p) return;
      const list = partnersByRoute.get(a.route_id as string) ?? [];
      list.push(p);
      partnersByRoute.set(a.route_id as string, list);
    });

    return rows.map((r): Route => {
      const path = (r.path as LatLng[]) ?? [];
      const partners = partnersByRoute.get(r.id as string) ?? [];
      return {
        id: r.id as string,
        name: r.name as string,
        territory: r.territory as string,
        status: (r.status as Route["status"]) ?? "scheduled",
        assignedMarketers: partners,
        assignedRepId: partners[0]?.id,
        assignedRepName: partners.map((p) => p.name.split(" ")[0]).join(" & ") || undefined,
        center: centerOf(path),
        path,
        doorsPlanned: (r.doors_planned as number) ?? 0,
        doorsHit: (r.doors_hit as number) ?? 0,
        answered: (r.answered as number) ?? 0,
        leads: (r.leads as number) ?? 0,
        coverage: (r.coverage_pct as number) ?? 0,
        createdAt: r.created_at as string,
        scheduledFor: (r.scheduled_for as string) ?? undefined,
        areaInput: (r.area_input as string) ?? undefined,
        generationId: (r.generation_id as string) ?? undefined,
      };
    });
  },

  getRoute: async (id: string): Promise<Route | null> => {
    const all = await data.getRoutes();
    return all.find((r) => r.id === id) ?? null;
  },

  getShifts: async (): Promise<Shift[]> => {
    const db = supabaseRead();
    if (!db) return [];
    const { data: rows } = await db.from("D2D_Shifts").select("*").order("date", { ascending: true });
    if (!rows?.length) return [];
    const marketerIds = [...new Set(rows.map((s) => s.marketer_id as string))];
    const { data: marketers } = await db
      .from("D2D_Marketers")
      .select("id,name,avatar_tint,home_territory")
      .in("id", marketerIds);
    const mById = new Map<string, Record<string, unknown>>();
    (marketers ?? []).forEach((m) => mById.set(m.id as string, m));

    return rows.map((s): Shift => {
      const m = mById.get(s.marketer_id as string);
      return {
        id: s.id as string,
        repId: s.marketer_id as string,
        repName: (m?.name as string) ?? "Unassigned",
        tint: tint(m?.avatar_tint),
        routeId: (s.route_id as string) ?? undefined,
        territory: (m?.home_territory as string) ?? "",
        date: s.date as string,
        start: s.start_time as string,
        end: s.end_time as string,
        status: (s.status as Shift["status"]) ?? "scheduled",
        notes: (s.notes as string) ?? undefined,
      };
    });
  },

  getRouteGeneration: async (id: string): Promise<RouteGeneration | null> => {
    const db = supabaseRead();
    if (!db) return null;
    const { data: row } = await db
      .from("D2D_RouteGenerations")
      .select("*")
      .eq("id", id)
      .maybeSingle();
    if (!row) return null;
    return {
      id: row.id as string,
      areaInput: row.area_input as string,
      status: (row.status as RouteGeneration["status"]) ?? "queued",
      stage: (row.stage as string) ?? "queued",
      progress: (row.progress as number) ?? 0,
      agentSummary: (row.agent_summary as string) ?? undefined,
      error: (row.error as string) ?? undefined,
      createdAt: row.created_at as string,
      completedAt: (row.completed_at as string) ?? undefined,
      preview: (row.preview as RouteGeneration["preview"]) ?? null,
    };
  },

  getLeads: async (): Promise<Lead[]> => {
    const db = supabaseRead();
    if (!db) return [];
    const { data: rows } = await db
      .from("D2D_Leads")
      .select("*")
      .order("created_at", { ascending: false });
    if (!rows?.length) return [];
    const marketerIds = [...new Set(rows.map((l) => l.marketer_id).filter(Boolean))] as string[];
    const { data: marketers } = marketerIds.length
      ? await db.from("D2D_Marketers").select("id,name,home_territory").in("id", marketerIds)
      : { data: [] as Record<string, unknown>[] };
    const mById = new Map<string, Record<string, unknown>>();
    (marketers ?? []).forEach((m) => mById.set(m.id as string, m));

    return rows.map((r) => {
      const m = r.marketer_id ? mById.get(r.marketer_id as string) : undefined;
      return mapLead(r, {
        repName: (m?.name as string) ?? "Unassigned",
        territory: m?.home_territory as string,
      });
    });
  },
  getLead: async (id: string): Promise<Lead | null> => {
    const all = await data.getLeads();
    return all.find((l) => l.id === id) ?? null;
  },
  getSessions: async (): Promise<Session[]> => {
    const db = supabaseRead();
    if (!db) return [];
    const { data: rows } = await db
      .from("D2D_Sessions")
      .select("*")
      .order("started_at", { ascending: false });
    return hydrateSessions(db, rows ?? []);
  },

  getLiveSessions: async (): Promise<Session[]> => {
    const db = supabaseRead();
    if (!db) return [];
    const { data: rows } = await db
      .from("D2D_Sessions")
      .select("*")
      .eq("status", "live")
      .order("started_at", { ascending: false });
    return hydrateSessions(db, rows ?? []);
  },

  getSession: async (id: string): Promise<Session | null> => {
    const db = supabaseRead();
    if (!db) return null;
    const { data: row } = await db.from("D2D_Sessions").select("*").eq("id", id).maybeSingle();
    if (!row) return null;
    const [session] = await hydrateSessions(db, [row]);
    return session ?? null;
  },

  /** Ordered transcript for a session - the manager page's initial server render
   *  before Supabase Realtime takes over streaming new lines. */
  getSessionTranscript: async (id: string): Promise<TranscriptLine[]> => {
    const db = supabaseRead();
    if (!db) return [];
    const { data: rows } = await db
      .from("D2D_TranscriptLines")
      .select("*")
      .eq("session_id", id)
      .order("seq", { ascending: true });
    return (rows ?? []).map(mapTranscriptLine);
  },

  /** Latest transcript lines per session - seeds the live sessions grid's
   *  per-rep conversation peek before Realtime streams new lines. */
  getLatestLines: async (
    sessionIds: string[],
    perSession = 4,
  ): Promise<Record<string, TranscriptLine[]>> => {
    const out: Record<string, TranscriptLine[]> = {};
    const db = supabaseRead();
    if (!db || !sessionIds.length) return out;
    const { data: rows } = await db
      .from("D2D_TranscriptLines")
      .select("session_id,id,at,created_at,speaker,text,sentiment,seq")
      .in("session_id", sessionIds)
      .eq("is_final", true)
      .order("seq", { ascending: true });
    for (const r of rows ?? []) {
      const sid = r.session_id as string;
      (out[sid] ??= []).push(mapTranscriptLine(r));
    }
    for (const sid of Object.keys(out)) out[sid] = out[sid].slice(-perSession);
    return out;
  },

  /** Agent insights for a session (objection/script-adherence/coaching/tone +
   *  the grade summary) - seeds the live agent panel before Realtime streams new
   *  ones, and shows the full grading for a completed session on load. */
  getSessionInsights: async (id: string): Promise<AgentInsight[]> => {
    const db = supabaseRead();
    if (!db) return [];
    const { data: rows } = await db
      .from("D2D_AgentInsights")
      .select("*")
      .eq("session_id", id)
      .order("at", { ascending: true });
    return (rows ?? []).map(
      (r): AgentInsight => ({
        id: r.id as string,
        at: (r.at as string) ?? (r.created_at as string),
        kind: (r.kind as AgentInsight["kind"]) ?? "coaching",
        title: (r.title as string) ?? "",
        detail: (r.detail as string) ?? "",
        score: typeof r.score === "number" ? (r.score as number) : undefined,
        objectionId: (r.objection_id as string) ?? undefined,
      }),
    );
  },

  /** Leads auto-detected (or manually added) for one session - seeds the manager
   *  view's detected-leads panel on load, before Realtime streams new ones. */
  getSessionLeads: async (id: string): Promise<Lead[]> => {
    const db = supabaseRead();
    if (!db) return [];
    const { data: rows } = await db
      .from("D2D_Leads")
      .select("*")
      .eq("session_id", id)
      .order("created_at", { ascending: true });
    return (rows ?? []).map((r) => mapLead(r, { defaultSource: "auto-detected" }));
  },

  /** Door pins for one session - the coverage map's `trail`. */
  getSessionDoors: async (id: string): Promise<DoorPing[]> => {
    const db = supabaseRead();
    if (!db) return [];
    const { data: rows } = await db
      .from("D2D_DoorEvents")
      .select("*")
      .eq("session_id", id)
      .order("at", { ascending: true });
    return (rows ?? []).map(mapDoor);
  },

  /** All recent door pins across sessions - powers the team coverage map. */
  getAllDoors: async (limit = 3000): Promise<DoorPing[]> => {
    const db = supabaseRead();
    if (!db) return [];
    const { data: rows } = await db
      .from("D2D_DoorEvents")
      .select("*")
      .order("at", { ascending: false })
      .limit(limit);
    return (rows ?? []).map(mapDoor);
  },

  /** Past (non-live) sessions, newest first - powers per-marketer history. */
  getRecentSessions: async (limit = 100): Promise<Session[]> => {
    const db = supabaseRead();
    if (!db) return [];
    const { data: rows } = await db
      .from("D2D_Sessions")
      .select("*")
      .neq("status", "live")
      .order("started_at", { ascending: false })
      .limit(limit);
    return hydrateSessions(db, rows ?? []);
  },

  getPlaybook: async (): Promise<Playbook | null> => {
    const db = supabaseRead();
    if (!db) return null;
    const { data: row } = await db
      .from("D2D_Playbooks")
      .select("*")
      .order("created_at", { ascending: true })
      .limit(1)
      .maybeSingle();
    if (!row) return null;
    return {
      scriptTitle: (row.script_title as string) ?? "Cold Approach Script",
      script: (row.script as string) ?? "",
      objections: (row.objections as Playbook["objections"]) ?? [],
      gradingCriteria: (row.grading_criteria as Playbook["gradingCriteria"]) ?? [],
    };
  },
  getDashboard: async (): Promise<DashboardData> => emptyDashboard,
};
