import { EquipmentAgent } from "../agents/equipment-agent.js";
import { RoutingAgent } from "../agents/routing-agent.js";
import { CrewAssignmentAgent } from "../agents/crew-assignment-agent.js";
import { SchedulerAgent } from "../agents/scheduler-agent.js";
import { ClientCommunicationsAgent } from "../agents/client-communications-agent.js";
import type { Agent } from "../agents/base.js";
import type { AgentPriorResults } from "../agents/base.js";
import type { AgentResult, PlanningContext, ProductionWeek } from "../domain/types.js";

export interface PlannerRunResult {
  week: ProductionWeek;
  agentResults: AgentPriorResults;
  durationMs: number;
}

/**
 * Orchestrates specialists in dependency order. Each agent reads
 * prior agents' outputs — mimicking how a dispatcher team hands off work.
 *
 * Pipeline:
 *   Equipment → Routing → Crew Assignment → Scheduler → Client Comms
 */
export class ProductionWeekPlanner {
  private readonly pipeline: Agent[];

  constructor(agents?: Agent[]) {
    this.pipeline =
      agents ??
      [
        new EquipmentAgent(),
        new RoutingAgent(),
        new CrewAssignmentAgent(),
        new SchedulerAgent(),
        new ClientCommunicationsAgent(),
      ];
  }

  async plan(ctx: PlanningContext): Promise<PlannerRunResult> {
    const started = Date.now();
    const agentResults: AgentPriorResults = {};
    const allWarnings: string[] = [];

    for (const agent of this.pipeline) {
      const output = await agent.run(ctx, agentResults);
      agentResults[agent.name] = output;
      allWarnings.push(...output.warnings);
    }

    const scheduler = agentResults.SchedulerAgent?.data as {
      blocks: ProductionWeek["blocks"];
      unassignedJobIds: string[];
    };
    const comms = agentResults.ClientCommunicationsAgent?.data as {
      actions: ProductionWeek["clientActions"];
    };
    const crewPlan = agentResults.CrewAssignmentAgent?.data as {
      crewRemainingHours: Record<string, number>;
    };

    const crewUtilization: ProductionWeek["crewUtilization"] = {};
    for (const crew of ctx.crews) {
      const scheduled =
        crew.weeklyHourBudget - (crewPlan?.crewRemainingHours[crew.id] ?? crew.weeklyHourBudget);
      crewUtilization[crew.id] = {
        scheduled: Math.round(scheduled * 10) / 10,
        budget: crew.weeklyHourBudget,
      };
    }

    for (const agentResult of Object.values(agentResults)) {
      allWarnings.push(...(agentResult as AgentResult<unknown>).warnings);
    }

    const week: ProductionWeek = {
      weekStart: ctx.weekStart,
      blocks: scheduler?.blocks ?? [],
      unassignedJobIds: scheduler?.unassignedJobIds ?? [],
      crewUtilization,
      warnings: [...new Set(allWarnings)],
      clientActions: comms?.actions ?? [],
    };

    return {
      week,
      agentResults,
      durationMs: Date.now() - started,
    };
  }
}
