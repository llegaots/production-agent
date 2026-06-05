import type { LatLng } from "@/lib/types";
import type { GeoBounds, StreetSegment } from "./types";
import { pointInPolygon } from "./util";

const ENDPOINTS = [
  "https://overpass.kumi.systems/api/interpreter",
  "https://overpass-api.de/api/interpreter",
  "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
  "https://overpass.openstreetmap.ru/api/interpreter",
];

// Residential street classes only - streets that actually front homes.
const HIGHWAY = "residential|living_street";

// Building values that are NOT a dwelling/door.
const NON_HOME = new Set([
  "garage", "garages", "carport", "shed", "roof", "greenhouse", "hut", "cabin",
  "commercial", "industrial", "retail", "office", "warehouse", "kiosk", "supermarket",
  "school", "university", "college", "kindergarten", "hospital", "clinic",
  "church", "cathedral", "chapel", "mosque", "synagogue", "temple", "religious",
  "civic", "public", "government", "hotel", "motel", "parking", "fire_station",
  "hangar", "barn", "farm_auxiliary", "stable", "service", "transformer_tower",
  "construction", "ruins", "tower", "water_tower", "silo", "bunker",
]);

interface OverpassEl {
  type: string;
  id: number;
  tags?: Record<string, string>;
  geometry?: { lat: number; lon: number }[];
  center?: { lat: number; lon: number };
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function runQuery(endpoint: string, query: string, timeoutMs = 40000): Promise<OverpassEl[]> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "RouteIQ/1.0 (D2D route planner; ops@routeiq.app)",
      },
      body: "data=" + encodeURIComponent(query),
      signal: ctrl.signal,
    });
    if (res.status === 429 || res.status === 503 || res.status === 504) {
      const e = new Error(`Overpass busy (HTTP ${res.status})`) as Error & { busy?: boolean; retryAfter?: number };
      e.busy = true;
      const ra = Number(res.headers.get("retry-after"));
      e.retryAfter = Number.isFinite(ra) ? ra : undefined;
      throw e;
    }
    if (!res.ok) throw new Error(`Overpass HTTP ${res.status}`);
    const json = (await res.json()) as { elements: OverpassEl[] };
    return json.elements ?? [];
  } finally {
    clearTimeout(timer);
  }
}

export interface AreaData {
  streets: StreetSegment[];
  homes: LatLng[];
}

/** Fetch residential streets + home building footprints within a bbox. When a
 *  boundary `polygon` is given (e.g. the postal-code shape), coverage is clipped
 *  to inside it - streets touching it are kept whole, homes must be inside. */
export async function fetchAreaData(bounds: GeoBounds, polygon?: LatLng[][]): Promise<AreaData> {
  const { minLat, minLng, maxLat, maxLng } = bounds;
  const bbox = `${minLat},${minLng},${maxLat},${maxLng}`;
  const query = `[out:json][timeout:40];
(way["highway"~"${HIGHWAY}"]["highway"!~"service"](${bbox}););
out geom;
(way["building"](${bbox}); rel["building"](${bbox}););
out center;`;

  let busyHits = 0;
  let lastErr: unknown;

  for (let round = 0; round < 3; round++) {
    for (const endpoint of ENDPOINTS) {
      try {
        const els = await runQuery(endpoint, query);
        const streets: StreetSegment[] = [];
        const homes: LatLng[] = [];
        for (const el of els) {
          if (el.tags?.highway && el.geometry && el.geometry.length >= 2) {
            streets.push({
              id: `way-${el.id}`,
              name: el.tags.name,
              points: el.geometry.map((g) => ({ lat: g.lat, lng: g.lon })),
            });
          } else if (el.tags?.building && el.center) {
            const b = el.tags.building;
            if (!NON_HOME.has(b)) homes.push({ lat: el.center.lat, lng: el.center.lon });
          }
        }
        if (polygon?.length) {
          const cs = streets.filter((s) => s.points.some((p) => pointInPolygon(p, polygon)));
          const ch = homes.filter((h) => pointInPolygon(h, polygon));
          // only apply the clip if it didn't nuke the area (bad/zero-overlap polygon)
          if (cs.length) return { streets: cs, homes: ch };
        }
        return { streets, homes };
      } catch (err) {
        lastErr = err;
        if ((err as { busy?: boolean })?.busy) {
          busyHits++;
          const wait = Math.min(((err as { retryAfter?: number })?.retryAfter ?? 1.5 * (round + 1)) * 1000, 6000);
          await sleep(wait);
        }
      }
    }
  }

  throw new Error(
    busyHits > 0
      ? "OpenStreetMap's servers are rate-limiting right now (HTTP 429). Wait ~30s and try again, or try a more specific postal code."
      : `Could not fetch map data from OpenStreetMap: ${lastErr instanceof Error ? lastErr.message : String(lastErr)}`,
  );
}
