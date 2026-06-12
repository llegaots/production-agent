import type { LatLng } from "@/lib/types";
import { pointInPolygon, pointToSegment } from "./util";

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

export interface ParcelCandidate {
  id: number;
  ring: LatLng[];
}

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
  /** what today's pipeline (Nominatim + 60 m snap) would record */
  current: {
    address: string | null;
    /** Nominatim resolved an actual house number */
    exact: boolean;
    /** where the pin would be snapped (null = kept raw GPS) */
    snapped: LatLng | null;
    snapDistanceM: number | null;
  } | null;
  /** all nearby footprints, for drawing on the map */
  candidates: ParcelCandidate[];
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

/** Fetch building footprints around a point from OSM Overpass, sorted by
 *  distance (an "inside" hit sorts first at 0 m). */
export async function buildingsAround(p: LatLng, radiusM = 90): Promise<OsmBuilding[]> {
  const q = `[out:json][timeout:10];way(around:${radiusM},${p.lat},${p.lng})["building"];out tags geom;`;
  const res = await fetch("https://overpass-api.de/api/interpreter", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: "data=" + encodeURIComponent(q),
  });
  if (!res.ok) throw new Error(`Overpass failed (HTTP ${res.status})`);
  const j = (await res.json()) as { elements?: OverpassWay[] };

  const out: OsmBuilding[] = [];
  for (const el of j.elements ?? []) {
    if (el.type !== "way" || !el.geometry || el.geometry.length < 3) continue;
    const ring = el.geometry.map((g) => ({ lat: g.lat, lng: g.lon }));
    // average the vertices for a centroid (skip the closing duplicate)
    const closed =
      ring.length > 1 &&
      ring[0].lat === ring[ring.length - 1].lat &&
      ring[0].lng === ring[ring.length - 1].lng;
    const verts = closed ? ring.slice(0, -1) : ring;
    const centroid = {
      lat: verts.reduce((s, v) => s + v.lat, 0) / verts.length,
      lng: verts.reduce((s, v) => s + v.lng, 0) / verts.length,
    };
    const inside = pointInPolygon(p, [ring]);
    out.push({
      id: el.id,
      ring,
      centroid,
      tags: el.tags ?? {},
      inside,
      distanceM: inside ? 0 : distanceToRing(p, ring),
    });
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

/** Reverse geocode via the Google Geocoding API (rooftop quality where
 *  available). Returns null when no key is configured or nothing resolves. */
export async function googleReverse(p: LatLng): Promise<GoogleReverse | null> {
  const key = process.env.GOOGLE_MAPS_API_KEY || process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY;
  if (!key) return null;
  try {
    const url =
      `https://maps.googleapis.com/maps/api/geocode/json?latlng=` +
      `${encodeURIComponent(p.lat)},${encodeURIComponent(p.lng)}&key=${key}`;
    const res = await fetch(url);
    if (!res.ok) return null;
    const j = (await res.json()) as {
      status?: string;
      results?: {
        formatted_address: string;
        types: string[];
        geometry?: { location_type?: string };
      }[];
    };
    if (j.status !== "OK" || !j.results?.length) return null;
    const best =
      j.results.find((r) => r.types.includes("street_address") || r.types.includes("premise")) ??
      j.results[0];
    return {
      address: best.formatted_address,
      locationType: best.geometry?.location_type ?? "UNKNOWN",
    };
  } catch {
    return null;
  }
}
