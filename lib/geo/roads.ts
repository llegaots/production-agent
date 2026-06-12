import "server-only";
import type { LatLng } from "@/lib/types";

const KEY = process.env.GOOGLE_GEOCODING_API_KEY;

/** True when road-snapping is available (reuses the server Google key). */
export const roadsConfigured = () => Boolean(KEY);

interface SnappedPoint {
  location: { latitude: number; longitude: number };
}

/** Snap a GPS path onto the road network with Google Roads API, interpolating the
 *  road geometry so the trail follows streets instead of cutting corners. The API
 *  takes up to 100 points per call, so we snap the most recent 100 (the part the
 *  manager is watching) and keep older points as-is. Falls back to the raw points
 *  when no key is set or the call fails. */
export async function snapToRoads(points: LatLng[]): Promise<LatLng[]> {
  if (!KEY || points.length < 2) return points;
  const recent = points.slice(-100);
  const older = points.slice(0, points.length - recent.length);
  const path = recent.map((p) => `${p.lat},${p.lng}`).join("|");
  try {
    const res = await fetch(
      `https://roads.googleapis.com/v1/snapToRoads?interpolate=true&path=${encodeURIComponent(path)}&key=${KEY}`,
    );
    if (!res.ok) return points;
    const j = (await res.json()) as { snappedPoints?: SnappedPoint[] };
    const snapped = (j.snappedPoints ?? []).map((s) => ({ lat: s.location.latitude, lng: s.location.longitude }));
    return snapped.length >= 2 ? [...older, ...snapped] : points;
  } catch {
    return points;
  }
}
