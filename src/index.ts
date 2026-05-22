import { ProductionWeekPlanner } from "./orchestrator/production-planner.js";
import { samplePlanningContext } from "./data/sample-week.js";

async function main() {
  const planner = new ProductionWeekPlanner();
  const { week, agentResults, durationMs } = await planner.plan(
    samplePlanningContext
  );

  console.log("\n═══ Production Week Plan ═══\n");
  console.log(`Week of ${week.weekStart}  (${durationMs}ms planner run)\n`);

  console.log("── Crew utilization ──");
  for (const [crewId, u] of Object.entries(week.crewUtilization)) {
    const pct = Math.round((u.scheduled / u.budget) * 100);
    console.log(`  ${crewId}: ${u.scheduled}h / ${u.budget}h (${pct}%)`);
  }

  console.log("\n── Schedule ──");
  const byDate = new Map<string, typeof week.blocks>();
  for (const b of week.blocks) {
    const list = byDate.get(b.date) ?? [];
    list.push(b);
    byDate.set(b.date, list);
  }
  for (const [date, blocks] of [...byDate.entries()].sort()) {
    console.log(`\n  ${date}`);
    for (const b of blocks.sort((a, c) => a.startTime.localeCompare(c.startTime))) {
      const job = samplePlanningContext.jobs.find((j) => j.id === b.jobId);
      console.log(
        `    ${b.startTime}–${b.endTime}  [${b.crewId}]  ${job?.title ?? b.jobId}` +
          (b.travelFromPreviousMinutes > 0
            ? `  (+${b.travelFromPreviousMinutes}m drive)`
            : "")
      );
    }
  }

  if (week.unassignedJobIds.length) {
    console.log("\n── Unassigned ──");
    for (const id of week.unassignedJobIds) {
      console.log(`  ${id}`);
    }
  }

  console.log("\n── Agent insights ──");
  for (const [, res] of Object.entries(agentResults)) {
    for (const i of res.insights) {
      console.log(`  [${i.agent}] ${i.summary}`);
    }
  }

  console.log("\n── Client confirmations & reschedules ──");
  for (const action of week.clientActions) {
    console.log(`  ${action.type.toUpperCase()} ${action.jobId}:`);
    console.log(`    ${action.message.replace(/\n/g, " ")}`);
  }

  if (week.warnings.length) {
    console.log("\n── Warnings ──");
    for (const w of week.warnings) console.log(`  ⚠ ${w}`);
  }

  console.log("");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
