import type { Agent } from "./base.js";
import { insight, result } from "./base.js";
import type { AgentPriorResults } from "./base.js";
import type {
  AgentResult,
  PlanningContext,
  ScheduledBlock,
} from "../domain/types.js";
import { estimateDriveMinutes } from "../domain/geo.js";
import type { CrewAssignmentPlan } from "./crew-assignment-agent.js";
import type { RoutingPlan } from "./routing-agent.js";

const WORK_START = "07:30";
const WORK_END = "16:30";

export interface SchedulerOutput {
  blocks: ScheduledBlock[];
  unassignedJobIds: string[];
}

/**
 * Builds day-by-day blocks: respects crew assignments, clusters jobs
 * on the same day when possible, and inserts travel between stops.
 */
export class SchedulerAgent implements Agent<PlanningContext, SchedulerOutput> {
  readonly name = "SchedulerAgent";

  async run(
    ctx: PlanningContext,
    prior?: AgentPriorResults
  ): Promise<AgentResult<SchedulerOutput>> {
    const assignment = prior?.CrewAssignmentAgent?.data as
      | CrewAssignmentPlan
      | undefined;
    const routing = prior?.RoutingAgent?.data as RoutingPlan | undefined;

    const matchByJob = new Map(
      assignment?.matches.map((m) => [m.jobId, m.crewId]) ?? []
    );

    const jobsByCrew = new Map<string, string[]>();
    for (const [jobId, crewId] of matchByJob) {
      const list = jobsByCrew.get(crewId) ?? [];
      list.push(jobId);
      jobsByCrew.set(crewId, list);
    }

    const jobById = new Map(ctx.jobs.map((j) => [j.id, j]));
    const crewById = new Map(ctx.crews.map((c) => [c.id, c]));
    const weekDates = weekDatesFromStart(ctx.weekStart);

    const blocks: ScheduledBlock[] = [];
    const unassigned: string[] = [];
    const warnings: string[] = [];

    for (const crew of ctx.crews) {
      const jobIds = jobsByCrew.get(crew.id) ?? [];
      if (jobIds.length === 0) continue;

      const ordered = orderJobsForCrew(jobIds, routing, jobById);
      let dayIndex = 0;
      let minutesIntoDay = timeToMinutes(WORK_START);
      let lastLocation = crew.homeBase;

      for (const jobId of ordered) {
        const job = jobById.get(jobId);
        if (!job) continue;

        const drive = estimateDriveMinutes(lastLocation, job.location);
        const blockMinutes = Math.round(job.estimatedHours * 60) + drive;

        if (minutesIntoDay + blockMinutes > timeToMinutes(WORK_END)) {
          dayIndex++;
          minutesIntoDay = timeToMinutes(WORK_START);
          lastLocation = crew.homeBase;
          if (dayIndex >= weekDates.length) {
            unassigned.push(jobId);
            warnings.push(`No slot left in week for ${jobId} on ${crew.name}`);
            continue;
          }
        }

        const date = weekDates[dayIndex]!;
        const startTime = minutesToTime(minutesIntoDay);
        const endMinutes =
          minutesIntoDay + drive + Math.round(job.estimatedHours * 60);
        const endTime = minutesToTime(endMinutes);

        blocks.push({
          jobId,
          crewId: crew.id,
          date,
          startTime,
          endTime,
          travelFromPreviousMinutes: drive,
        });

        minutesIntoDay = Math.round(endMinutes);
        lastLocation = job.location;
      }
    }

    for (const job of ctx.jobs) {
      if (
        job.status !== "cancelled" &&
        job.status !== "completed" &&
        !blocks.some((b) => b.jobId === job.id)
      ) {
        if (!unassigned.includes(job.id)) unassigned.push(job.id);
      }
    }

    return result(
      this.name,
      { blocks, unassignedJobIds: unassigned },
      [
        insight(
          this.name,
          `Scheduled ${blocks.length} blocks across ${weekDates.length} days`,
          summarizeByDay(blocks)
        ),
      ],
      warnings
    );
  }
}

function orderJobsForCrew(
  jobIds: string[],
  routing: RoutingPlan | undefined,
  jobById: Map<string, { id: string; location: { lat: number; lng: number } }>
): string[] {
  if (!routing || jobIds.length <= 1) return jobIds;

  for (const cluster of routing.clusters) {
    const inCluster = jobIds.filter((id) => cluster.jobIds.includes(id));
    if (inCluster.length === jobIds.length) {
      return cluster.jobIds.filter((id) => jobIds.includes(id));
    }
  }

  const ordered: string[] = [];
  const pool = new Set(jobIds);
  let currentId = jobIds[0]!;
  ordered.push(currentId);
  pool.delete(currentId);

  while (pool.size > 0) {
    const neighbors = routing.proximity[currentId] ?? [];
    const next =
      neighbors.find((id) => pool.has(id)) ?? [...pool][0]!;
    ordered.push(next);
    pool.delete(next);
    currentId = next;
  }

  return ordered;
}

function weekDatesFromStart(weekStart: string): string[] {
  const start = new Date(weekStart + "T12:00:00");
  return Array.from({ length: 5 }, (_, i) => {
    const d = new Date(start);
    d.setDate(d.getDate() + i);
    return d.toISOString().slice(0, 10);
  });
}

function timeToMinutes(t: string): number {
  const [h, m] = t.split(":").map(Number);
  return h! * 60 + m!;
}

function minutesToTime(min: number): string {
  const total = Math.round(min);
  const h = Math.floor(total / 60);
  const m = total % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

function summarizeByDay(blocks: ScheduledBlock[]): string[] {
  const byDay = new Map<string, number>();
  for (const b of blocks) {
    byDay.set(b.date, (byDay.get(b.date) ?? 0) + 1);
  }
  return [...byDay.entries()].map(([d, n]) => `${d}: ${n} jobs`);
}
