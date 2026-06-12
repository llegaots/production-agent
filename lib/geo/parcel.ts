import { mkdir, readFile, writeFile } from "fs/promises";
import path from "path";
import type { LatLng } from "@/lib/types";
import { haversine, pointInPolygon, pointToSegment } from "./util";

/* -----------------------------------------------------------------------------
   Parcel / building-footprint resolution: instead of asking "what is the
   nearest address to this GPS point?" (today's pipeline), we ask "which
   building's footprint does this point fall inside (or sit closest to)?".
   A point-in-polygon hit is deterministic, so it survives GPS noise that a
   nearest-geocode lookup does not.
   Footprints come from OSM via Overpass (free, no key). The matched
   building's address resolves through a chain: OSM addr tags, then Google
   rooftop reverse geocoding, then Nominatim.
----------------------------------------------------------------------------- */

export interface ParcelMatch {
  ring: LatLng[];
  centroid: LatLng;
  /** true when the pin is inside the footprint (the strong signal) */
  inside: boolean;
  /** 0 when inside, else meters from the pin to the footprint's edge */
  distanceM: number;
  address: string | null;
  addressSource: "osm" | "google" | "nominatim" | null;
}

export interface GoogleReverse {
  address: string;
  /** ROOFTOP, RANGE_INTERPOLATED, GEOMETRIC_CENTER or APPROXIMATE */
  locationType: string;
}

export interface ParcelLocateResponse {
  pin: LatLng;
  /** the new method: building footprint point-in-polygon */
  parcel: ParcelMatch | null;
  /** Google reverse geocode of the raw pin (geocoder-swap comparison) */
  google: GoogleReverse | null;
  /** Do the two methods name the same home? "agree" = same house number;
   *  "alias" = different records that forward-geocode to the same physical
   *  home (duplicate municipal data); "conflict" = genuinely different
   *  buildings, the case production would flag as unverified. */
  verdict: "agree" | "alias" | "conflict" | null;
  /** set when the footprint source (Overpass) was unreachable */
  parcelError: string | null;
}

interface OverpassWay {
  type: string;
  id: number;
  tags?: Record<string, string>;
  geometry?: { lat: number; lon: number }[];
}

export interface OsmBuilding {
  id: number;
  ring: LatLng[];
  centroid: LatLng;
  tags: Record<string, string>;
  inside: boolean;
  distanceM: number;
}

/** Min distance (m) from a point to the polygon's edges. */
function distanceToRing(p: LatLng, ring: LatLng[]): number {
  let min = Infinity;
  for (let i = 0; i < ring.length - 1; i++) {
    const d = pointToSegment(p, ring[i], ring[i + 1]);
    if (d < min) min = d;
  }
  return min;
}

/* Overpass requires a User-Agent identifying the app (same policy as
   Nominatim); requests without one are rejected. Mirrors are tried in order:
   kumi first because the main overpass-api.de instance rate-limits per IP and
   starts returning 504s under rapid use. */
const OVERPASS_ENDPOINTS = [
  "https://overpass.kumi.systems/api/interpreter",
  "https://overpass-api.de/api/interpreter",
  "https://overpass.private.coffee/api/interpreter",
];

/** Per-mirror time cap so one hanging server can't stall the lookup. */
const OVERPASS_ATTEMPT_TIMEOUT_MS = 12000;

interface RawBuilding {
  id: number;
  ring: LatLng[];
  centroid: LatLng;
  tags: Record<string, string>;
}

/* Footprints are cached per ~550 m grid cell (roughly one neighborhood) so a
   whole QA session downloads from OSM a handful of times, not per click (the
   public Overpass servers throttle repeat callers). Cells persist to disk so
   restarts keep the cache warm, stale data is served when OSM is unreachable
   (buildings do not move), and concurrent clicks share one in-flight fetch. */
const CELL_DEG = 0.005;
const CELL_FETCH_RADIUS_M = 450;
const CACHE_TTL_MS = 7 * 24 * 60 * 60 * 1000;
const CACHE_MAX_CELLS = 50;
const CACHE_DIR = path.join(process.cwd(), ".footprint-cache");
const cellCache = new Map<string, { at: number; buildings: RawBuilding[] }>();
const inFlight = new Map<string, Promise<RawBuilding[]>>();

async function fetchBuildingsRaw(center: LatLng, radiusM: number): Promise<RawBuilding[]> {
  const q = `[out:json][timeout:10];way(around:${radiusM},${center.lat},${center.lng})["building"];out tags geom;`;
  let res: Response | null = null;
  let lastError = "no endpoint reachable";
  for (const endpoint of OVERPASS_ENDPOINTS) {
    try {
      const attempt = await fetch(endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
          "User-Agent": "RouteIQ/1.0 (D2D field intelligence; contact: ops@routeiq.app)",
          Accept: "application/json",
        },
        body: "data=" + encodeURIComponent(q),
        signal: AbortSignal.timeout(OVERPASS_ATTEMPT_TIMEOUT_MS),
      });
      if (attempt.ok) {
        res = attempt;
        break;
      }
      lastError = `HTTP ${attempt.status}`;
    } catch (e) {
      lastError = e instanceof Error ? e.message : String(e);
    }
  }
  if (!res) throw new Error(`Overpass failed (${lastError})`);
  const j = (await res.json()) as { elements?: OverpassWay[] };

  const out: RawBuilding[] = [];
  for (const el of j.elements ?? []) {
    if (el.type !== "way" || !el.geometry || el.geometry.length < 3) continue;
    const ring = el.geometry.map((g) => ({ lat: g.lat, lng: g.lon }));
    // average the vertices for a centroid (skip the closing duplicate)
    const closed =
      ring.length > 1 &&
      ring[0].lat === ring[ring.length - 1].lat &&
      ring[0].lng === ring[ring.length - 1].lng;
    const verts = closed ? ring.slice(0, -1) : ring;
    out.push({
      id: el.id,
      ring,
      centroid: {
        lat: verts.reduce((s, v) => s + v.lat, 0) / verts.length,
        lng: verts.reduce((s, v) => s + v.lng, 0) / verts.length,
      },
      tags: el.tags ?? {},
    });
  }
  return out;
}

async function readCellFromDisk(key: string): Promise<{ at: number; buildings: RawBuilding[] } | null> {
  try {
    const raw = await readFile(path.join(CACHE_DIR, `${key}.json`), "utf8");
    const parsed = JSON.parse(raw) as { at: number; buildings: RawBuilding[] };
    return Array.isArray(parsed.buildings) ? parsed : null;
  } catch {
    return null;
  }
}

async function writeCellToDisk(key: string, entry: { at: number; buildings: RawBuilding[] }) {
  try {
    await mkdir(CACHE_DIR, { recursive: true });
    await writeFile(path.join(CACHE_DIR, `${key}.json`), JSON.stringify(entry), "utf8");
  } catch {
    // cache persistence is best-effort; the lookup already succeeded
  }
}

function rememberCell(key: string, entry: { at: number; buildings: RawBuilding[] }) {
  cellCache.set(key, entry);
  if (cellCache.size > CACHE_MAX_CELLS) {
    const oldest = [...cellCache.entries()].sort((a, b) => a[1].at - b[1].at)[0];
    if (oldest) cellCache.delete(oldest[0]);
  }
}

async function buildingsForCell(p: LatLng): Promise<RawBuilding[]> {
  const cellLat = Math.floor(p.lat / CELL_DEG);
  const cellLng = Math.floor(p.lng / CELL_DEG);
  const key = `${cellLat},${cellLng}`;
  const now = Date.now();

  const memory = cellCache.get(key);
  if (memory && now - memory.at < CACHE_TTL_MS) return memory.buildings;

  const disk = memory ? null : await readCellFromDisk(key);
  if (disk && now - disk.at < CACHE_TTL_MS) {
    rememberCell(key, disk);
    return disk.buildings;
  }

  // One network fetch per cold cell, shared by concurrent clicks.
  const pending = inFlight.get(key);
  if (pending) return pending;
  const fetchPromise = (async () => {
    const center = { lat: (cellLat + 0.5) * CELL_DEG, lng: (cellLng + 0.5) * CELL_DEG };
    try {
      const buildings = await fetchBuildingsRaw(center, CELL_FETCH_RADIUS_M);
      const entry = { at: now, buildings };
      rememberCell(key, entry);
      void writeCellToDisk(key, entry);
      return buildings;
    } catch (e) {
      // OSM unreachable: stale footprints beat none (buildings do not move).
      const stale = memory ?? disk;
      if (stale) {
        rememberCell(key, stale);
        return stale.buildings;
      }
      throw e;
    } finally {
      inFlight.delete(key);
    }
  })();
  inFlight.set(key, fetchPromise);
  return fetchPromise;
}

/** Building footprints near a point, sorted by distance to it (an "inside"
 *  hit sorts first at 0 m). Served from the per-cell cache when warm. */
export async function buildingsAround(p: LatLng, radiusM = 90): Promise<OsmBuilding[]> {
  const raw = await buildingsForCell(p);
  const out: OsmBuilding[] = [];
  for (const b of raw) {
    const inside = pointInPolygon(p, [b.ring]);
    const distanceM = inside ? 0 : distanceToRing(p, b.ring);
    if (distanceM > radiusM) continue;
    out.push({ ...b, inside, distanceM });
  }
  out.sort((a, b) => a.distanceM - b.distanceM);
  return out;
}

/** "123 Main St, City" from a building's own OSM address tags, if mapped. */
export function osmAddress(tags: Record<string, string>): string | null {
  const street = [tags["addr:housenumber"], tags["addr:street"]].filter(Boolean).join(" ");
  if (!street || !tags["addr:housenumber"]) return null;
  const city = tags["addr:city"];
  return city ? `${street}, ${city}` : street;
}

interface GoogleReverseCandidate {
  address: string;
  location: LatLng;
  locationType: string;
  /** a real address result (street_address or premise), not an area */
  isAddress: boolean;
}

/** All results Google returns for a reverse geocode, each with its own
 *  address-point coordinate. Empty when no key is configured or nothing
 *  resolves. */
async function googleReverseAll(p: LatLng): Promise<GoogleReverseCandidate[]> {
  const key =
    process.env.GOOGLE_GEOCODING_API_KEY || process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY;
  if (!key) return [];
  try {
    const url =
      `https://maps.googleapis.com/maps/api/geocode/json?latlng=` +
      `${encodeURIComponent(p.lat)},${encodeURIComponent(p.lng)}&key=${key}`;
    const res = await fetch(url);
    if (!res.ok) return [];
    const j = (await res.json()) as {
      status?: string;
      results?: {
        formatted_address: string;
        types: string[];
        geometry?: { location?: { lat: number; lng: number }; location_type?: string };
      }[];
    };
    if (j.status !== "OK" || !j.results?.length) return [];
    return j.results
      .filter((r) => r.geometry?.location)
      .map((r) => ({
        address: r.formatted_address,
        location: { lat: r.geometry!.location!.lat, lng: r.geometry!.location!.lng },
        locationType: r.geometry?.location_type ?? "UNKNOWN",
        isAddress: r.types.includes("street_address") || r.types.includes("premise"),
      }));
  } catch {
    return [];
  }
}

/** Reverse geocode via the Google Geocoding API (rooftop quality where
 *  available). Returns null when no key is configured or nothing resolves. */
export async function googleReverse(p: LatLng): Promise<GoogleReverse | null> {
  const all = await googleReverseAll(p);
  const best = all.find((r) => r.isAddress) ?? all[0];
  return best ? { address: best.address, locationType: best.locationType } : null;
}

/** First house number in an address string ("66 All. White Pine, ..." -> "66"). */
export function houseNumber(address: string | null | undefined): string | null {
  if (!address) return null;
  const m = address.match(/\d+/);
  return m ? m[0] : null;
}

/** Forward geocode an address to its point, for the alias check (two address
 *  records landing on the same spot are one physical home). */
export async function googleForward(address: string): Promise<LatLng | null> {
  const key =
    process.env.GOOGLE_GEOCODING_API_KEY || process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY;
  if (!key) return null;
  try {
    const url =
      `https://maps.googleapis.com/maps/api/geocode/json?address=` +
      `${encodeURIComponent(address)}&key=${key}`;
    const res = await fetch(url);
    if (!res.ok) return null;
    const j = (await res.json()) as {
      status?: string;
      results?: { geometry?: { location?: { lat: number; lng: number } } }[];
    };
    const loc = j.status === "OK" ? j.results?.[0]?.geometry?.location : undefined;
    return loc ? { lat: loc.lat, lng: loc.lng } : null;
  } catch {
    return null;
  }
}

/** Address for a matched footprint. Google's first reverse-geocode answer is
 *  the nearest ADDRESS POINT, which on offset streets is often the neighbor;
 *  instead, prefer the result whose own coordinate lands inside the footprint,
 *  falling back to the address point closest to the centroid. */
export async function googleAddressForFootprint(
  ring: LatLng[],
  centroid: LatLng,
): Promise<GoogleReverse | null> {
  const candidates = (await googleReverseAll(centroid)).filter((r) => r.isAddress);
  if (!candidates.length) return null;
  const inside = candidates.find((r) => pointInPolygon(r.location, [ring]));
  const best =
    inside ??
    candidates.reduce((a, b) =>
      haversine(centroid, a.location) <= haversine(centroid, b.location) ? a : b,
    );
  return { address: best.address, locationType: best.locationType };
}
