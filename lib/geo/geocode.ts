import type { AddressConfidence, LatLng } from "@/lib/types";
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
 * Reverse-geocode a GPS point to the nearest home: its street address, the
 * building coordinate, and how much to trust it. Prefers Google Geocoding (best
 * Canadian house-number coverage + a ROOFTOP/interpolated quality flag) and
 * falls back to Nominatim when no Google key is set, so dev still works.
 */
export interface ReverseResult {
  /** "211 Sunny St, Baie-D'Urfe" style label, or null when nothing house-level resolves */
  address: string | null;
  /** the resolved building coordinate (caller decides whether to snap to it) */
  lat: number;
  lng: number;
  /** how trustworthy the match is */
  confidence: AddressConfidence;
  source: "google" | "nominatim";
  /** true when the match resolved to a specific house number */
  exact: boolean;
}

const GOOGLE_GEOCODING_KEY = process.env.GOOGLE_GEOCODING_API_KEY;

/** Google's `location_type` -> our trust level. */
function googleConfidence(locationType: string): AddressConfidence {
  if (locationType === "ROOFTOP") return "rooftop";
  if (locationType === "RANGE_INTERPOLATED") return "interpolated";
  return "gps-only"; // GEOMETRIC_CENTER / APPROXIMATE - too coarse to be a house
}

interface GoogleComponent {
  long_name: string;
  types: string[];
}
interface GoogleResult {
  formatted_address: string;
  address_components: GoogleComponent[];
  geometry: { location: { lat: number; lng: number }; location_type: string };
}

async function googleReverse(lat: number, lng: number): Promise<ReverseResult | null> {
  if (!GOOGLE_GEOCODING_KEY) return null;
  const url =
    `https://maps.googleapis.com/maps/api/geocode/json?latlng=${lat},${lng}` +
    `&result_type=street_address|premise|subpremise&key=${GOOGLE_GEOCODING_KEY}`;
  const res = await fetch(url);
  if (!res.ok) return null;
  const j = (await res.json()) as { status: string; results?: GoogleResult[] };
  // No house-level address nearby: keep the GPS point, mark it unresolved.
  if (j.status === "ZERO_RESULTS") {
    return { address: null, lat, lng, confidence: "gps-only", source: "google", exact: false };
  }
  if (j.status !== "OK" || !j.results?.length) return null;

  const pick =
    j.results.find((r) => r.address_components.some((c) => c.types.includes("street_number"))) ??
    j.results[0];
  const comp = (type: string) =>
    pick.address_components.find((c) => c.types.includes(type))?.long_name;
  const streetNo = comp("street_number");
  const route = comp("route");
  const city = comp("locality") ?? comp("sublocality") ?? comp("administrative_area_level_2");
  const street = [streetNo, route].filter(Boolean).join(" ");
  const address = [street || route, city].filter(Boolean).join(", ") || pick.formatted_address || null;
  return {
    address,
    lat: pick.geometry.location.lat,
    lng: pick.geometry.location.lng,
    confidence: googleConfidence(pick.geometry.location_type),
    source: "google",
    exact: Boolean(streetNo),
  };
}

async function nominatimReverse(lat: number, lng: number): Promise<ReverseResult | null> {
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
      // OSM address nodes aren't guaranteed rooftop, so never claim more than interpolated.
      confidence: a.house_number ? "interpolated" : "gps-only",
      source: "nominatim",
      exact: Boolean(a.house_number),
    };
  } catch {
    return null;
  }
}

/** Reverse-geocode a GPS point: Google first (rooftop + confidence), Nominatim fallback. */
export async function reverseGeocodeDetailed(lat: number, lng: number): Promise<ReverseResult | null> {
  if (GOOGLE_GEOCODING_KEY) {
    const g = await googleReverse(lat, lng);
    if (g) return g;
  }
  return nominatimReverse(lat, lng);
}

export async function reverseGeocode(lat: number, lng: number): Promise<string | null> {
  return (await reverseGeocodeDetailed(lat, lng))?.address ?? null;
}
