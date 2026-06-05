import "server-only";
import { planCoverage } from "@/lib/geo/plan";
import type { PaceModel } from "@/lib/geo/capacity";
import type { GeoBounds, StreetSegment } from "@/lib/geo/types";
import type { LatLng, PreviewRoute } from "@/lib/types";
import type { PlannerMarketer } from "./route-planner";

/** Everything needed to (re-)plan a preview without re-hitting OSM/geocoding. */
export interface GeoCache {
  area: string;
  date: string;
  displayName: string;
  center: LatLng;
  bounds: GeoBounds;
  streets: StreetSegment[];
  homes: LatLng[];
  marketers: PlannerMarketer[];
  /** pairings — groups of marketer ids that walk together */
  groups: string[][];
  /** per-group base time budget in seconds (from the session/shift length) */
  budgetsBaseSec: number[];
  pace: PaceModel;
}

/** Structured steering the AI emits to nudge a re-plan. */
export interface Steer {
  /** street-name substrings to drop from coverage */
  excludeStreets?: string[];
  /** street-name substrings to pull coverage toward (sets the growth seed) */
  focusStreets?: string[];
  /** nudge the whole area toward a compass direction */
  focusDirection?: "north" | "south" | "east" | "west" | "center";
  /** scale every route's size (e.g. 1.3 = ~30% bigger, 0.7 = smaller) */
  sizeFactor?: number;
}

const norm = (s: string) => s.toLowerCase().trim();

function midpointOfStreets(streets: StreetSegment[], names: string[]): LatLng | null {
  const wanted = names.map(norm).filter(Boolean);
  if (!wanted.length) return null;
  const pts: LatLng[] = [];
  for (const s of streets) {
    const n = norm(s.name ?? "");
    if (n && wanted.some((w) => n.includes(w))) pts.push(...s.points);
  }
  if (!pts.length) return null;
  const c = pts.reduce((a, p) => ({ lat: a.lat + p.lat, lng: a.lng + p.lng }), { lat: 0, lng: 0 });
  return { lat: c.lat / pts.length, lng: c.lng / pts.length };
}

function shiftCenter(center: LatLng, bounds: GeoBounds, dir: Steer["focusDirection"]): LatLng {
  if (!dir || dir === "center") return center;
  const dLat = (bounds.maxLat - bounds.minLat) * 0.3;
  const dLng = (bounds.maxLng - bounds.minLng) * 0.3;
  switch (dir) {
    case "north": return { lat: center.lat + dLat, lng: center.lng };
    case "south": return { lat: center.lat - dLat, lng: center.lng };
    case "east": return { lat: center.lat, lng: center.lng + dLng };
    case "west": return { lat: center.lat, lng: center.lng - dLng };
  }
}

/** Deterministically (re-)plan a preview from cached geometry + optional steering. */
export function planPreview(cache: GeoCache, steer: Steer = {}): { routes: PreviewRoute[]; totalHomes: number } {
  // 1. exclude streets the manager doesn't want
  let streets = cache.streets;
  if (steer.excludeStreets?.length) {
    const ex = steer.excludeStreets.map(norm).filter(Boolean);
    streets = streets.filter((s) => {
      const n = norm(s.name ?? "");
      return !(n && ex.some((e) => n.includes(e)));
    });
  }

  // 2. choose the seed center — focus street wins, else a direction nudge
  const focusPt = steer.focusStreets?.length ? midpointOfStreets(cache.streets, steer.focusStreets) : null;
  const center = focusPt ?? shiftCenter(cache.center, cache.bounds, steer.focusDirection);

  // 3. scale budgets (bigger / smaller routes)
  const factor = steer.sizeFactor && steer.sizeFactor > 0 ? Math.min(3, Math.max(0.3, steer.sizeFactor)) : 1;
  const budgets = cache.budgetsBaseSec.map((b) => b * factor);

  const peoplePerGroup = cache.groups.map((ids) => ids.length);
  const { zones, totalHomes } = planCoverage(streets, cache.homes, center, budgets, cache.pace, peoplePerGroup);

  const nameById = new Map(cache.marketers.map((m) => [m.id, m.name] as const));
  const short = (cache.displayName || cache.area).split(/[—,]/)[0].trim() || cache.area;

  const routes: PreviewRoute[] = [];
  for (let i = 0; i < zones.length; i++) {
    const zone = zones[i];
    if (zone.path.length < 2) continue;
    const ids = i === zones.length - 1 ? cache.groups.slice(i).flat() : cache.groups[i] ?? [];
    const label = zone.topStreets.slice(0, 2).join(" & ") || "Residential core";
    routes.push({
      tempId: `r${i}`,
      name: `${short} — ${label}`,
      territory: zone.topStreets[0] ?? short,
      topStreets: zone.topStreets,
      path: zone.path,
      center: zone.center,
      meet: zone.meet,
      doors: zone.doors,
      minutes: zone.minutes,
      marketerIds: ids,
      marketerNames: ids.map((id) => nameById.get(id) ?? "—"),
    });
  }
  return { routes, totalHomes };
}
