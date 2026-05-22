/** Core domain types for field-service production planning. */

export type JobDifficulty = "easy" | "standard" | "hard" | "specialty";
export type JobStatus =
  | "unscheduled"
  | "proposed"
  | "awaiting_client"
  | "confirmed"
  | "in_progress"
  | "completed"
  | "cancelled";

export type ConfirmationStatus =
  | "not_sent"
  | "pending"
  | "confirmed"
  | "declined"
  | "reschedule_requested";

export interface GeoPoint {
  lat: number;
  lng: number;
}

export interface Client {
  id: string;
  name: string;
  phone?: string;
  email?: string;
  preferredContact: "sms" | "email" | "phone";
  notes?: string;
}

export interface Equipment {
  id: string;
  name: string;
  quantity: number;
  /** Jobs requiring this equipment cannot run without it. */
  requiredForDifficulties?: JobDifficulty[];
}

export interface Crew {
  id: string;
  name: string;
  /** Weekly budget in billable hours (production target). */
  weeklyHourBudget: number;
  skills: JobDifficulty[];
  equipmentIds: string[];
  /** Typical start location (depot / first job area). */
  homeBase: GeoPoint;
}

export interface Job {
  id: string;
  clientId: string;
  title: string;
  address: string;
  location: GeoPoint;
  difficulty: JobDifficulty;
  /** Estimated on-site hours for this crew size. */
  estimatedHours: number;
  equipmentIds: string[];
  /** Earliest / latest acceptable service window. */
  windowStart: string;
  windowEnd: string;
  status: JobStatus;
  confirmationStatus: ConfirmationStatus;
  priority: 1 | 2 | 3 | 4 | 5;
  notes?: string;
}

export interface TravelLeg {
  fromJobId: string | "depot";
  toJobId: string;
  distanceKm: number;
  driveMinutes: number;
}

export interface ScheduledBlock {
  jobId: string;
  crewId: string;
  date: string;
  startTime: string;
  endTime: string;
  travelFromPreviousMinutes: number;
}

export interface ProductionWeek {
  weekStart: string;
  blocks: ScheduledBlock[];
  unassignedJobIds: string[];
  crewUtilization: Record<string, { scheduled: number; budget: number }>;
  warnings: string[];
  clientActions: ClientAction[];
}

export interface ClientAction {
  jobId: string;
  clientId: string;
  type: "confirm" | "reschedule" | "cancel_notice";
  message: string;
  proposedDate?: string;
  proposedStartTime?: string;
}

export interface PlanningContext {
  weekStart: string;
  jobs: Job[];
  crews: Crew[];
  equipment: Equipment[];
  clients: Client[];
  /** Jobs that must be replanned (weather, no-show, client request). */
  rescheduleJobIds?: string[];
}

export interface AgentInsight {
  agent: string;
  summary: string;
  details: string[];
  score?: number;
}

export interface AgentResult<T> {
  agent: string;
  data: T;
  insights: AgentInsight[];
  warnings: string[];
}
