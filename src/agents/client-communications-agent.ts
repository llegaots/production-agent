import type { Agent } from "./base.js";
import { insight, result } from "./base.js";
import type { AgentPriorResults } from "./base.js";
import type {
  AgentResult,
  Client,
  ClientAction,
  Job,
  PlanningContext,
  ScheduledBlock,
} from "../domain/types.js";
import type { SchedulerOutput } from "./scheduler-agent.js";

export interface ClientCommsPlan {
  actions: ClientAction[];
  /** Jobs that should not be executed until client confirms. */
  holdUntilConfirmed: string[];
}

/**
 * Owns confirmations and reschedules — the highest-risk operational step.
 * Produces outbound messages and flags jobs that need client approval
 * before the crew is dispatched.
 */
export class ClientCommunicationsAgent
  implements Agent<PlanningContext, ClientCommsPlan>
{
  readonly name = "ClientCommunicationsAgent";

  async run(
    ctx: PlanningContext,
    prior?: AgentPriorResults
  ): Promise<AgentResult<ClientCommsPlan>> {
    const schedule = prior?.SchedulerAgent?.data as SchedulerOutput | undefined;
    const blocks = schedule?.blocks ?? [];
    const blockByJob = new Map(blocks.map((b) => [b.jobId, b]));
    const clientById = new Map(ctx.clients.map((c) => [c.id, c]));

    const actions: ClientAction[] = [];
    const holdUntilConfirmed: string[] = [];
    const warnings: string[] = [];

    const rescheduleSet = new Set(ctx.rescheduleJobIds ?? []);

    for (const job of ctx.jobs) {
      if (job.status === "cancelled" || job.status === "completed") continue;

      const client = clientById.get(job.clientId);
      const block = blockByJob.get(job.id);

      if (rescheduleSet.has(job.id)) {
        actions.push(buildRescheduleAction(job, client, block));
        holdUntilConfirmed.push(job.id);
        continue;
      }

      if (job.confirmationStatus === "confirmed" && job.status === "confirmed") {
        continue;
      }

      if (!block) {
        if (job.confirmationStatus === "pending") {
          warnings.push(`Job ${job.id} pending confirmation but not scheduled`);
        }
        continue;
      }

      if (
        job.confirmationStatus === "not_sent" ||
        job.confirmationStatus === "pending" ||
        job.status === "proposed" ||
        job.status === "unscheduled"
      ) {
        actions.push(buildConfirmAction(job, client, block));
        holdUntilConfirmed.push(job.id);
      }

      if (job.confirmationStatus === "reschedule_requested") {
        actions.push(buildRescheduleAction(job, client, block));
        holdUntilConfirmed.push(job.id);
      }

      if (job.confirmationStatus === "declined") {
        warnings.push(`Client declined ${job.id} — remove from production week`);
      }
    }

    return result(
      this.name,
      { actions, holdUntilConfirmed },
      [
        insight(
          this.name,
          `${actions.length} client touchpoints (${holdUntilConfirmed.length} jobs on hold until confirmed)`,
          actions.slice(0, 5).map((a) => `${a.type}: ${a.message.slice(0, 60)}…`)
        ),
      ],
      warnings
    );
  }
}

function buildConfirmAction(
  job: Job,
  client: Client | undefined,
  block: ScheduledBlock
): ClientAction {
  const name = client?.name ?? "there";
  const channel = client?.preferredContact ?? "sms";
  const message =
    channel === "email"
      ? `Hi ${name},\n\nWe're scheduled to service ${job.title} at ${job.address} on ${block.date} between ${block.startTime} and ${block.endTime}.\n\nReply YES to confirm or let us know if you need a different time.\n\nThank you!`
      : `Hi ${name}! ${job.title} on ${block.date} ~${block.startTime}. Reply YES to confirm or text RESCHEDULE.`;

  return {
    jobId: job.id,
    clientId: job.clientId,
    type: "confirm",
    message,
    proposedDate: block.date,
    proposedStartTime: block.startTime,
  };
}

function buildRescheduleAction(
  job: Job,
  client: Client | undefined,
  block?: ScheduledBlock
): ClientAction {
  const name = client?.name ?? "there";
  const proposed = block
    ? ` We can offer ${block.date} at ${block.startTime}.`
    : " Please share a few times that work for you.";

  return {
    jobId: job.id,
    clientId: job.clientId,
    type: "reschedule",
    message: `Hi ${name}, we need to adjust your appointment for ${job.title}.${proposed}`,
    proposedDate: block?.date,
    proposedStartTime: block?.startTime,
  };
}
