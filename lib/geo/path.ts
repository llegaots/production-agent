import type { LatLng } from "@/lib/types";
import type { StreetSegment } from "./types";
import { haversine, midpoint, polylineLength, distanceToPolyline } from "./util";

/** Drop segments already covered by a recent route (within bufferMeters). */
export function filterCoveredSegments(
  segments: StreetSegment[],
  pastLines: LatLng[][],
  bufferMeters = 18,
): StreetSegment[] {
  if (!pastLines.length) return segments;
  return segments.filter((seg) => {
    const m = midpoint(seg);
    // covered if the street's midpoint sits on top of any past route line
    return !pastLines.some((line) => distanceToPolyline(m, line) <= bufferMeters);
  });
}

const first = (s: StreetSegment) => s.points[0];
const last = (s: StreetSegment) => s.points[s.points.length - 1];

/**
 * Greedy nearest-neighbour walking tour through a set of streets: start at the
 * SW-most street, then always hop to the nearest unused street endpoint,
 * flipping direction when that's shorter. Returns the ordered path + the total
 * street length (meters) used to size door counts.
 */
export function buildWalkingPath(segments: StreetSegment[]): { path: LatLng[]; meters: number } {
  if (!segments.length) return { path: [], meters: 0 };

  const used = new Array(segments.length).fill(false);
  // deterministic start: south-west-most segment start point
  let startIdx = 0;
  let best = Infinity;
  segments.forEach((s, i) => {
    const p = first(s);
    const score = p.lat + p.lng;
    if (score < best) {
      best = score;
      startIdx = i;
    }
  });

  const path: LatLng[] = [];
  let meters = 0;
  used[startIdx] = true;
  path.push(...segments[startIdx].points);
  meters += polylineLength(segments[startIdx].points);
  let cursor = last(segments[startIdx]);

  for (let step = 1; step < segments.length; step++) {
    let bestIdx = -1;
    let bestDist = Infinity;
    let flip = false;
    for (let i = 0; i < segments.length; i++) {
      if (used[i]) continue;
      const dStart = haversine(cursor, first(segments[i]));
      const dEnd = haversine(cursor, last(segments[i]));
      const d = Math.min(dStart, dEnd);
      if (d < bestDist) {
        bestDist = d;
        bestIdx = i;
        flip = dEnd < dStart;
      }
    }
    if (bestIdx === -1) break;
    used[bestIdx] = true;
    const pts = flip ? [...segments[bestIdx].points].reverse() : segments[bestIdx].points;
    path.push(...pts);
    meters += polylineLength(pts);
    cursor = pts[pts.length - 1];
  }

  return { path, meters };
}
