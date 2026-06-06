import type { LatLng } from "@/lib/types";
import type { StreetSegment } from "./types";
import { midpoint, distanceToPolyline } from "./util";

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
