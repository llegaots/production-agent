import type { Agent } from "./base.js";
import { insight, result } from "./base.js";
import type { AgentPriorResults } from "./base.js";
import type {
  AgentResult,
  Crew,
  Job,
  JobDifficulty,
  PlanningContext,
} from "../domain/types.js";
import type { EquipmentPlan } from "./equipment-agent.js";
import type { RoutingPlan } from "./routing-agent.js";

export interface CrewJobMatch {
  jobId: string;
  crewId: string;
  score: number;
  reasons: string[];
}

export interface CrewAssignmentPlan {
  matches: CrewJobMatch[];
  crewRemainingHours: Record<string, number>;
}

const DIFFICULTY_RANK: Record<JobDifficulty, number> = {
  easy: 1,
  standard: 2,
  hard: 3,
  specialty: 4,
};

/**
 * Matches jobs to crews by skill fit, difficulty, and remaining
 * weekly hour budget — the core production capacity constraint.
 */
export class CrewAssignmentAgent
  implements Agent<PlanningContext, CrewAssignmentPlan>
{
  readonly name = "CrewAssignmentAgent";

  async run(
    ctx: PlanningContext,
    prior?: AgentPriorResults
  ): Promise<AgentResult<CrewAssignmentPlan>> {
    const equipment = prior?.EquipmentAgent?.data as EquipmentPlan | undefined;
    const routing = prior?.RoutingAgent?.data as RoutingPlan | undefined;

    const feasibleJobIds = new Set(
      ctx.jobs
        .filter((j) => {
          if (j.status === "cancelled" || j.status === "completed") return false;
          const alloc = equipment?.allocations.find((a) => a.jobId === j.id);
          return alloc?.feasible !== false;
        })
        .map((j) => j.id)
    );

    const crewRemaining: Record<string, number> = {};
    for (const crew of ctx.crews) {
      crewRemaining[crew.id] = crew.weeklyHourBudget;
    }

    const jobs = ctx.jobs
      .filter((j) => feasibleJobIds.has(j.id))
      .sort((a, b) => b.priority - a.priority);

    const matches: CrewJobMatch[] = [];
    const warnings: string[] = [];

    const clusterCrewHint = buildClusterCrewHints(routing, ctx.crews);

    for (const job of jobs) {
      const candidates = scoreCrewsForJob(job, ctx.crews, crewRemaining, clusterCrewHint);
      const best = candidates[0];
      if (!best || best.score < 30) {
        warnings.push(`No suitable crew for job ${job.id} (${job.title})`);
        continue;
      }
      if (crewRemaining[best.crewId]! < job.estimatedHours) {
        warnings.push(
          `Crew ${best.crewId} over budget if assigned ${job.id}; still proposed with overtime flag`
        );
        best.reasons.push("exceeds weekly hour budget");
      }
      crewRemaining[best.crewId]! -= job.estimatedHours;
      matches.push({
        jobId: job.id,
        crewId: best.crewId,
        score: best.score,
        reasons: best.reasons,
      });
    }

    return result(
      this.name,
      { matches, crewRemainingHours: crewRemaining },
      [
        insight(
          this.name,
          `Assigned ${matches.length}/${jobs.length} feasible jobs to crews`,
          ctx.crews.map(
            (c) =>
              `${c.name}: ${c.weeklyHourBudget - (crewRemaining[c.id] ?? 0)}/${c.weeklyHourBudget}h scheduled`
          )
        ),
      ],
      warnings
    );
  }
}

function scoreCrewsForJob(
  job: Job,
  crews: Crew[],
  remaining: Record<string, number>,
  clusterHint: Record<string, string>
): { crewId: string; score: number; reasons: string[] }[] {
  return crews
    .map((crew) => {
      let score = 50;
      const reasons: string[] = [];

      if (crew.skills.includes(job.difficulty)) {
        score += 25;
        reasons.push(`skilled for ${job.difficulty}`);
      } else if (
        crew.skills.some(
          (s) => DIFFICULTY_RANK[s] >= DIFFICULTY_RANK[job.difficulty]
        )
      ) {
        score += 10;
        reasons.push("over-qualified crew");
      } else {
        score -= 40;
        reasons.push("crew lacks skill for difficulty");
      }

      const hasGear = job.equipmentIds.every((id) =>
        crew.equipmentIds.includes(id)
      );
      if (hasGear) {
        score += 15;
        reasons.push("carries required equipment");
      } else if (job.equipmentIds.length > 0) {
        score -= 20;
        reasons.push("equipment mismatch");
      }

      const hoursLeft = remaining[crew.id] ?? 0;
      if (hoursLeft >= job.estimatedHours) {
        score += 20;
        reasons.push(`${hoursLeft}h budget remaining`);
      } else {
        score -= 15;
        reasons.push(`only ${hoursLeft}h budget left`);
      }

      if (clusterHint[job.id] === crew.id) {
        score += 10;
        reasons.push("same area as crew's other cluster work");
      }

      return { crewId: crew.id, score, reasons };
    })
    .sort((a, b) => b.score - a.score);
}

function buildClusterCrewHints(
  routing: RoutingPlan | undefined,
  crews: Crew[]
): Record<string, string> {
  const hint: Record<string, string> = {};
  if (!routing) return hint;
  routing.clusters.forEach((cluster, idx) => {
    const crew = crews[idx % crews.length];
    if (!crew) return;
    for (const jobId of cluster.jobIds) {
      hint[jobId] = crew.id;
    }
  });
  return hint;
}
