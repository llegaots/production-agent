import type { AgentInsight, AgentResult, PlanningContext } from "../domain/types.js";

export type { AgentInsight, AgentResult, PlanningContext };

export interface Agent<TInput = PlanningContext, TOutput = unknown> {
  readonly name: string;
  run(input: TInput, prior?: AgentPriorResults): Promise<AgentResult<TOutput>>;
}

export interface AgentPriorResults {
  [agentName: string]: AgentResult<unknown>;
}

export function insight(
  agent: string,
  summary: string,
  details: string[] = [],
  score?: number
): AgentInsight {
  return { agent, summary, details, score };
}

export function result<T>(
  agent: string,
  data: T,
  insights: AgentInsight[] = [],
  warnings: string[] = []
): AgentResult<T> {
  return { agent, data, insights, warnings };
}
