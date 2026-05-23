/** Mirrors Supabase rows / schedule_preview jsonb — source of truth is always Supabase. */

export type ChatSession = {
  id: string;
  title: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type ChatMessage = {
  id: string;
  session_id: string;
  sequence_number: number;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  tool_calls: unknown[];
  tool_results: unknown;
  schedule_preview: SchedulePreview | null;
  schedule_run_id: string | null;
  created_at: string;
};

export type RouteStop = {
  job_id: string;
  node_index: number;
  arrival_minute: number;
  start_minute: number;
  depart_minute: number;
};

export type CrewRoute = {
  crew_id: string;
  stops: RouteStop[];
  total_travel_minutes: number;
  total_service_minutes: number;
  end_minute: number;
};

export type SchedulePreview = {
  type: "schedule_preview";
  schedule_run_id: string;
  status: string;
  approved: boolean;
  needs_human_review: boolean;
  week_start: string;
  week_end: string;
  iteration_count: number;
  summary: string;
  attempt_id: string | null;
  assigned_job_ids: string[];
  unassigned_job_ids: string[];
  routes: CrewRoute[];
  issues: string[];
};

export type ScheduleRun = {
  id: string;
  status: string;
  approved: boolean;
  iteration_count: number;
  summary: string;
  week_start: string;
  week_end: string;
};

export type ScheduleRunIteration = {
  id: string;
  schedule_run_id: string;
  iteration_number: number;
  approved: boolean;
  feedback_prompt: string;
  issues: string[];
  created_at: string;
};

export type JobRow = {
  id: string;
  address: string;
  client_id: string;
  estimated_minutes: number;
};

export type CrewRow = {
  id: string;
  name: string;
};
