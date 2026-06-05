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
 * Geocode a postal code (or neighbourhood) to a center, bounding box, and — when
 * OSM has it — the area's real boundary polygon, using Nominatim (free, no key).
 * Nominatim policy: send a descriptive User-Agent, ≤ 1 req/sec.
 */
export async function geocodeArea(input: string): Promise<GeocodeResult> {
  const q = input.trim();
  if (!q) throw new Error("Area is required");

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

  const arr = (await res.json()) as Array<{
    lat: string;
    lon: string;
    display_name: string;
    boundingbox: [string, string, string, string]; // [south, north, west, east]
    geojson?: GeoJson;
  }>;
  if (!arr.length)
    throw new Error(`No location found for "${q}". For a postal code, try the area with the city, e.g. "${q}, Toronto".`);

  const r = arr[0];
  const [south, north, west, east] = r.boundingbox.map(Number);
  return {
    displayName: r.display_name,
    center: { lat: Number(r.lat), lng: Number(r.lon) },
    bounds: { minLat: south, maxLat: north, minLng: west, maxLng: east },
    polygon: outerRings(r.geojson),
  };
}
