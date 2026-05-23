import { getApiBase } from "@/lib/api-base";

export type OptimizerLabJob = {
  id: string;
  client_id: string;
  service_type: string;
  address: string;
  lat: number;
  lng: number;
  estimated_minutes: number;
  earliest_date: string;
  latest_date: string;
  required_skills: string[];
  required_equipment: string[];
  status: string;
  notes?: string;
};

export type OptimizerLabCrew = {
  crew_id: string;
  name: string;
  is_available: boolean;
  skills: string[];
  shift_start_minute: number;
  shift_end_minute: number;
};

export type RouteStop = {
  job_id: string;
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

export type OptimizerRunResult = {
  target_date: string;
  status: string;
  assigned_count: number;
  unassigned_count: number;
  assigned_job_ids: string[];
  unassigned_job_ids: string[];
  routes: CrewRoute[];
  messages: string[];
  equipment_check: Record<string, unknown> | null;
  duration_seconds: number;
};

export type JobListParams = {
  id_prefix?: string;
  id_from?: string;
  id_to?: string;
  target_date?: string;
  limit?: number;
};

const FETCH_TIMEOUT_MS = 20_000;

async function labFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const res = await fetch(`${getApiBase()}${path}`, {
      ...init,
      signal: controller.signal,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(
        text ? text.slice(0, 300) : `Request failed: ${res.status} ${res.statusText}`,
      );
    }
    return res.json() as Promise<T>;
  } catch (e) {
    if (e instanceof Error && e.name === "AbortError") {
      throw new Error(
        "Backend request timed out. Is FastAPI running on port 8000? Start: cd backend && PYTHONPATH=. uvicorn app.main:app --host 127.0.0.1 --port 8000",
      );
    }
    if (e instanceof TypeError && e.message.includes("fetch")) {
      throw new Error(
        "Cannot reach API. Start the backend (port 8000) and frontend (port 3000), then reload.",
      );
    }
    throw e;
  } finally {
    clearTimeout(timeout);
  }
}

export function fetchLabJobs(params: JobListParams) {
  const q = new URLSearchParams();
  if (params.id_prefix) q.set("id_prefix", params.id_prefix);
  if (params.id_from) q.set("id_from", params.id_from);
  if (params.id_to) q.set("id_to", params.id_to);
  if (params.target_date) q.set("target_date", params.target_date);
  if (params.limit) q.set("limit", String(params.limit));
  return labFetch<OptimizerLabJob[]>(`/optimizer-lab/jobs?${q}`);
}

export function updateLabJob(jobId: string, body: Partial<OptimizerLabJob>) {
  return labFetch<OptimizerLabJob>(`/optimizer-lab/jobs/${jobId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function deleteLabJob(jobId: string) {
  return labFetch<{ deleted: string }>(`/optimizer-lab/jobs/${jobId}`, { method: "DELETE" });
}

export function fetchLabCrews(targetDate: string) {
  return labFetch<OptimizerLabCrew[]>(
    `/optimizer-lab/crews?target_date=${encodeURIComponent(targetDate)}`,
  );
}

export function runLabOptimizer(body: {
  target_date: string;
  job_ids: string[];
  crew_ids?: string[];
  time_limit_seconds?: number;
}) {
  return labFetch<OptimizerRunResult>("/optimizer-lab/run", {
    method: "POST",
    body: JSON.stringify(body),
  });
}
