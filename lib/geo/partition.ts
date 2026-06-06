import type { LatLng } from "@/lib/types";
import type { StreetSegment } from "./types";
import { midpoint, segmentLength } from "./util";

export interface Zone {
  index: number;
  segments: StreetSegment[];
  meters: number;
  centroid: LatLng;
}

const dist2 = (a: LatLng, b: LatLng) => (a.lat - b.lat) ** 2 + (a.lng - b.lng) ** 2;

/**
 * Partition streets into `k` spatially-contiguous zones with k-means over street
 * midpoints. Deterministic seeding (farthest-point) so the same area yields the
 * same split. Each zone is one territory for a pair of marketers.
 */
export function partitionStreets(segments: StreetSegment[], k: number): Zone[] {
  const n = segments.length;
  const zones = Math.max(1, Math.min(k, n));
  const mids = segments.map(midpoint);

  // farthest-point seeding
  const seeds: LatLng[] = [mids[0]];
  while (seeds.length < zones) {
    let bestIdx = 0;
    let bestD = -1;
    for (let i = 0; i < n; i++) {
      const d = Math.min(...seeds.map((s) => dist2(mids[i], s)));
      if (d > bestD) {
        bestD = d;
        bestIdx = i;
      }
    }
    seeds.push(mids[bestIdx]);
  }

  let centroids = seeds;
  let assign = new Array(n).fill(0);
  for (let iter = 0; iter < 20; iter++) {
    let moved = false;
    for (let i = 0; i < n; i++) {
      let best = 0;
      let bestD = Infinity;
      for (let c = 0; c < zones; c++) {
        const d = dist2(mids[i], centroids[c]);
        if (d < bestD) {
          bestD = d;
          best = c;
        }
      }
      if (assign[i] !== best) {
        assign[i] = best;
        moved = true;
      }
    }
    // recompute centroids
    const sum = Array.from({ length: zones }, () => ({ lat: 0, lng: 0, n: 0 }));
    for (let i = 0; i < n; i++) {
      const c = assign[i];
      sum[c].lat += mids[i].lat;
      sum[c].lng += mids[i].lng;
      sum[c].n += 1;
    }
    centroids = centroids.map((c, ci) =>
      sum[ci].n ? { lat: sum[ci].lat / sum[ci].n, lng: sum[ci].lng / sum[ci].n } : c,
    );
    if (!moved) break;
  }

  const result: Zone[] = Array.from({ length: zones }, (_, i) => ({
    index: i,
    segments: [],
    meters: 0,
    centroid: centroids[i],
  }));
  segments.forEach((seg, i) => {
    const z = result[assign[i]];
    z.segments.push(seg);
    z.meters += segmentLength(seg);
  });

  return result.filter((z) => z.segments.length > 0);
}
