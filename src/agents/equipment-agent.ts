import type { Agent } from "./base.js";
import { insight, result } from "./base.js";
import type { AgentResult, Equipment, Job, PlanningContext } from "../domain/types.js";

export interface EquipmentAllocation {
  jobId: string;
  equipmentIds: string[];
  feasible: boolean;
  missing?: string[];
}

export interface EquipmentPlan {
  allocations: EquipmentAllocation[];
  dailyLoad: Record<string, Record<string, number>>;
}

/**
 * Ensures each job has required gear and tracks inventory so crews
 * are not double-booked on scarce equipment (water-fed poles, lifts, etc.).
 */
export class EquipmentAgent implements Agent<PlanningContext, EquipmentPlan> {
  readonly name = "EquipmentAgent";

  async run(ctx: PlanningContext): Promise<AgentResult<EquipmentPlan>> {
    const inventory = new Map(ctx.equipment.map((e) => [e.id, e.quantity]));
    const allocations: EquipmentAllocation[] = [];
    const warnings: string[] = [];

    for (const job of ctx.jobs) {
      const missing: string[] = [];
      for (const eqId of job.equipmentIds) {
        const eq = ctx.equipment.find((e) => e.id === eqId);
        if (!eq) {
          missing.push(eqId);
          continue;
        }
        if (eq.quantity < 1) missing.push(eq.name);
        if (
          eq.requiredForDifficulties?.includes(job.difficulty) &&
          eq.quantity === 0
        ) {
          missing.push(eq.name);
        }
      }
      const feasible = missing.length === 0;
      allocations.push({
        jobId: job.id,
        equipmentIds: job.equipmentIds,
        feasible,
        missing: missing.length ? missing : undefined,
      });
      if (!feasible) {
        warnings.push(
          `Job ${job.id} (${job.title}): missing equipment — ${missing.join(", ")}`
        );
      }
    }

    const dailyLoad: EquipmentPlan["dailyLoad"] = {};
    for (const eq of ctx.equipment) {
      dailyLoad[eq.id] = {};
    }

    const insights = [
      insight(
        this.name,
        `${allocations.filter((a) => a.feasible).length}/${allocations.length} jobs have equipment available`,
        ctx.equipment.map(
          (e) => `${e.name}: ${e.quantity} unit(s) in inventory`
        )
      ),
    ];

    return result(this.name, { allocations, dailyLoad }, insights, warnings);
  }
}

export function jobNeedsEquipment(job: Job, equipment: Equipment[]): string[] {
  return job.equipmentIds.filter((id) => {
    const eq = equipment.find((e) => e.id === id);
    return eq && eq.quantity < 1;
  });
}
