import type { LatLng } from "@/lib/types";
import type { GeocodeResult } from "./types";

type GeoJson =
  | { type: "Polygon"; coordinates: number[][][] }
  | { type: "MultiPolygon"; coordinates: number[][][][] }
  | { type: string; coordinates: unknown };

/** Extract the outer ring(s) of a GeoJSON polygon as LatLng rings (holes dropped). */
function outerRings(gj?: GeoJson): LatLng[][] | undefined {
  if (!gj) return undefined;
  const toRing = (ring: number[][]): LatLng[] => ring.map(([lng, lat]) => ({ lat, lng }));
  if (gj.type === "Polygon") {
    const c = gj.coordinates as number[][][];
    return c[0] ? [toRing(c[0])] : undefined;
  }
  if (gj.type === "MultiPolygon") {
    const c = gj.coordinates as number[][][][];
    const rings = c.map((poly) => poly[0]).filter(Boolean).map(toRing);
    return rings.length ? rings : undefined;
  }
  return undefined;
}

/**
 * Geocode a postal code (or neighbourhood) to a center, bounding box, and - when
 * OSM has it - the area's real boundary polygon, using Nominatim (free, no key).
 * Nominatim policy: send a descriptive User-Agent, ≤ 1 req/sec.
 */
interface NomResult {
  lat: string;
  lon: string;
  display_name: string;
  boundingbox: [string, string, string, string]; // [south, north, west, east]
  geojson?: GeoJson;
}

async function nominatim(q: string): Promise<NomResult | null> {
  const url =
    "https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&addressdetails=0&polygon_geojson=1&q=" +
    encodeURIComponent(q);
  const res = await fetch(url, {
    headers: {
      "User-Agent": "RouteIQ/1.0 (D2D route planner; contact: ops@routeiq.app)",
      "Accept-Language": "en",
    },
  });
  if (!res.ok) throw new Error(`Geocoding failed (HTTP ${res.status})`);
  const arr = (await res.json()) as NomResult[];
  return arr[0] ?? null;
}

const isCanadianFSA = (q: string) => /^[A-Za-z]\d[A-Za-z]\b/.test(q.trim());

export async function geocodeArea(input: string): Promise<GeocodeResult> {
  const q = input.trim();
  if (!q) throw new Error("Area is required");

  // Bare Canadian postal codes (e.g. "H9W") don't resolve on their own; add the
  // country (and try a province-agnostic form) before giving up.
  const variants = [q];
  if (isCanadianFSA(q) && !/canada/i.test(q)) variants.push(`${q}, Canada`);

  let r: NomResult | null = null;
  for (const v of variants) {
    r = await nominatim(v);
    if (r) break;
  }
  if (!r)
    throw new Error(`No location found for "${q}". Pick a suggestion from the search, or add the city, e.g. "${q}, Montreal".`);

  const [south, north, west, east] = r.boundingbox.map(Number);
  return {
    displayName: r.display_name,
    center: { lat: Number(r.lat), lng: Number(r.lon) },
    bounds: { minLat: south, maxLat: north, minLng: west, maxLng: east },
    polygon: outerRings(r.geojson),
  };
}

/**
 * Reverse-geocode a GPS point to a street address using Nominatim (free, no key).
 * Returns a concise "123 Main St, City" string, or null if nothing resolves.
 */
export interface ReverseResult {
  /** "211 Sunny St, Baie-D'Urfe" style label */
  address: string | null;
  /** the matched home/building's own coordinate (snapped off the road) */
  lat: number;
  lng: number;
  /** true when the match resolved to a specific house number */
  exact: boolean;
}

/** Reverse-geocode a GPS point to the nearest home: its address AND the home's
 *  own coordinate, so a door pin lands on the house rather than the road. */
export async function reverseGeocodeDetailed(lat: number, lng: number): Promise<ReverseResult | null> {
  try {
    const url =
      `https://nominatim.openstreetmap.org/reverse?format=jsonv2&zoom=18&addressdetails=1` +
      `&lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lng)}`;
    const res = await fetch(url, {
      headers: {
        "User-Agent": "RouteIQ/1.0 (D2D field intelligence; contact: ops@routeiq.app)",
        "Accept-Language": "en",
      },
    });
    if (!res.ok) return null;
    const j = (await res.json()) as {
      display_name?: string;
      lat?: string;
      lon?: string;
      address?: Record<string, string>;
    };
    const a = j.address ?? {};
    const street = [a.house_number, a.road].filter(Boolean).join(" ");
    const city = a.city || a.town || a.village || a.hamlet || a.suburb;
    const parts = [street || a.road, city].filter(Boolean);
    const snapLat = j.lat ? Number(j.lat) : lat;
    const snapLng = j.lon ? Number(j.lon) : lng;
    return {
      address: parts.length ? parts.join(", ") : (j.display_name ?? null),
      lat: Number.isFinite(snapLat) ? snapLat : lat,
      lng: Number.isFinite(snapLng) ? snapLng : lng,
      exact: Boolean(a.house_number),
    };
  } catch {
    return null;
  }
}

export async function reverseGeocode(lat: number, lng: number): Promise<string | null> {
  return (await reverseGeocodeDetailed(lat, lng))?.address ?? null;
}
