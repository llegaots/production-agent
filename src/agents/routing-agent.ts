import type { Agent } from "./base.js";
import { insight, result } from "./base.js";
import type { AgentPriorResults } from "./base.js";
import type { AgentResult, Job, PlanningContext } from "../domain/types.js";
import { distanceKm, estimateDriveMinutes } from "../domain/geo.js";

export interface JobCluster {
  clusterId: string;
  jobIds: string[];
  centroidLabel: string;
  totalDriveMinutesIfOrdered: number;
}

export interface RoutingPlan {
  clusters: JobCluster[];
  /** jobId -> sorted neighbor job ids by proximity */
  proximity: Record<string, string[]>;
  pairDriveMinutes: Record<string, number>;
}

/**
 * Groups jobs geographically and scores travel so schedulers
 * avoid zig-zagging across the city in one day.
 */
export class RoutingAgent implements Agent<PlanningContext, RoutingPlan> {
  readonly name = "RoutingAgent";

  async run(
    ctx: PlanningContext,
    _prior?: AgentPriorResults
  ): Promise<AgentResult<RoutingPlan>> {
    const activeJobs = ctx.jobs.filter((j) => j.status !== "cancelled");
    const proximity: Record<string, string[]> = {};
    const pairDriveMinutes: Record<string, number> = {};

    for (const a of activeJobs) {
      const neighbors = activeJobs
        .filter((b) => b.id !== a.id)
        .map((b) => ({
          id: b.id,
          km: distanceKm(a.location, b.location),
          min: estimateDriveMinutes(a.location, b.location),
        }))
        .sort((x, y) => x.km - y.km);
      proximity[a.id] = neighbors.slice(0, 5).map((n) => n.id);
      for (const n of neighbors) {
        pairDriveMinutes[`${a.id}->${n.id}`] = n.min;
      }
    }

    const clusters = buildClusters(activeJobs);
    const warnings: string[] = [];
    for (const c of clusters) {
      if (c.jobIds.length > 6) {
        warnings.push(
          `Cluster ${c.clusterId} has ${c.jobIds.length} jobs — consider splitting across days`
        );
      }
    }

    const avgDrive =
      clusters.reduce((s, c) => s + c.totalDriveMinutesIfOrdered, 0) /
      Math.max(1, clusters.length);

    return result(
      this.name,
      { clusters, proximity, pairDriveMinutes },
      [
        insight(
          this.name,
          `Formed ${clusters.length} geographic clusters; ~${Math.round(avgDrive)} min drive per cluster day`,
          clusters.map(
            (c) =>
              `${c.centroidLabel}: ${c.jobIds.length} jobs, ~${c.totalDriveMinutesIfOrdered} min travel`
          ),
          Math.max(0, 100 - avgDrive)
        ),
      ],
      warnings
    );
  }
}

function buildClusters(jobs: Job[]): JobCluster[] {
  const remaining = new Set(jobs.map((j) => j.id));
  const byId = new Map(jobs.map((j) => [j.id, j]));
  const clusters: JobCluster[] = [];
  let clusterIndex = 0;

  while (remaining.size > 0) {
    const seedId = [...remaining].sort(
      (a, b) => (byId.get(b)!.priority) - (byId.get(a)!.priority)
    )[0];
    const seed = byId.get(seedId)!;
    remaining.delete(seedId);

    const clusterJobs: Job[] = [seed];
    const maxRadiusKm = 8;

    for (const id of [...remaining]) {
      const job = byId.get(id)!;
      const nearSeed = distanceKm(seed.location, job.location) <= maxRadiusKm;
      const nearAny = clusterJobs.some(
        (c) => distanceKm(c.location, job.location) <= maxRadiusKm
      );
      if (nearSeed || nearAny) {
        clusterJobs.push(job);
        remaining.delete(id);
      }
    }

    const ordered = orderByNearestNeighbor(clusterJobs, seed.location);
    let drive = 0;
    for (let i = 1; i < ordered.length; i++) {
      drive += estimateDriveMinutes(
        ordered[i - 1]!.location,
        ordered[i]!.location
      );
    }

    clusters.push({
      clusterId: `cluster-${++clusterIndex}`,
      jobIds: ordered.map((j) => j.id),
      centroidLabel: seed.address.split(",")[0] ?? seed.address,
      totalDriveMinutesIfOrdered: drive,
    });
  }

  return clusters;
}

function orderByNearestNeighbor(jobs: Job[], start: Job["location"]): Job[] {
  const ordered: Job[] = [];
  const pool = [...jobs];
  let current = start;

  while (pool.length > 0) {
    pool.sort(
      (a, b) =>
        distanceKm(current, a.location) - distanceKm(current, b.location)
    );
    const next = pool.shift()!;
    ordered.push(next);
    current = next.location;
  }

  return ordered;
}
