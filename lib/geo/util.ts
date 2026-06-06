import type { LatLng } from "@/lib/types";
import type { GeoBounds, StreetSegment } from "./types";

const R = 6371000; // earth radius, meters
const rad = (d: number) => (d * Math.PI) / 180;

/** Great-circle distance in meters. */
export function haversine(a: LatLng, b: LatLng): number {
  const dLat = rad(b.lat - a.lat);
  const dLng = rad(b.lng - a.lng);
  const lat1 = rad(a.lat);
  const lat2 = rad(b.lat);
  const h =
    Math.sin(dLat / 2) ** 2 + Math.sin(dLng / 2) ** 2 * Math.cos(lat1) * Math.cos(lat2);
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}

export function polylineLength(points: LatLng[]): number {
  let total = 0;
  for (let i = 1; i < points.length; i++) total += haversine(points[i - 1], points[i]);
  return total;
}

export function segmentLength(seg: StreetSegment): number {
  return polylineLength(seg.points);
}

export function midpoint(seg: StreetSegment): LatLng {
  const pts = seg.points;
  const m = pts[Math.floor(pts.length / 2)];
  return m ?? { lat: 0, lng: 0 };
}

export function boundsCenter(b: GeoBounds): LatLng {
  return { lat: (b.minLat + b.maxLat) / 2, lng: (b.minLng + b.maxLng) / 2 };
}

/** Build a bounding box of the given radius (km) around a center point. */
export function boundsFromCenter(center: LatLng, radiusKm: number): GeoBounds {
  const latHalf = radiusKm / 111;
  const lngHalf = radiusKm / (111 * Math.cos(rad(center.lat)) || 1);
  return {
    minLat: center.lat - latHalf,
    maxLat: center.lat + latHalf,
    minLng: center.lng - lngHalf,
    maxLng: center.lng + lngHalf,
  };
}

/** Clamp a bbox to a max span (km) around its center - keeps Overpass fast. */
export function clampBounds(b: GeoBounds, maxSpanKm = 3): GeoBounds {
  const c = boundsCenter(b);
  const latHalf = maxSpanKm / 2 / 111; // ~111 km per degree latitude
  const lngHalf = maxSpanKm / 2 / (111 * Math.cos(rad(c.lat)) || 1);
  return {
    minLat: Math.max(b.minLat, c.lat - latHalf),
    maxLat: Math.min(b.maxLat, c.lat + latHalf),
    minLng: Math.max(b.minLng, c.lng - lngHalf),
    maxLng: Math.min(b.maxLng, c.lng + lngHalf),
  };
}

/** Ray-casting test: is point `p` inside the ring? (even-odd rule). */
function inRing(p: LatLng, ring: LatLng[]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i].lng, yi = ring[i].lat;
    const xj = ring[j].lng, yj = ring[j].lat;
    const hit = yi > p.lat !== yj > p.lat && p.lng < ((xj - xi) * (p.lat - yi)) / (yj - yi || 1e-12) + xi;
    if (hit) inside = !inside;
  }
  return inside;
}

/** Inside the area if inside any of its outer rings (multipolygon-safe). */
export function pointInPolygon(p: LatLng, rings: LatLng[][]): boolean {
  return rings.some((r) => r.length > 2 && inRing(p, r));
}

/** Min distance (m) from a point to a polyline, sampled at its vertices. */
export function distanceToPolyline(p: LatLng, line: LatLng[]): number {
  let min = Infinity;
  for (const v of line) {
    const d = haversine(p, v);
    if (d < min) min = d;
  }
  return min;
}

/** Perpendicular distance (m) from point p to segment a-b (equirectangular approx). */
export function pointToSegment(p: LatLng, a: LatLng, b: LatLng): number {
  const lat0 = rad((a.lat + b.lat) / 2);
  const mx = (lng: number) => rad(lng) * Math.cos(lat0) * R;
  const my = (lat: number) => rad(lat) * R;
  const px = mx(p.lng), py = my(p.lat);
  const ax = mx(a.lng), ay = my(a.lat);
  const bx = mx(b.lng), by = my(b.lat);
  const dx = bx - ax, dy = by - ay;
  const len2 = dx * dx + dy * dy;
  let t = len2 ? ((px - ax) * dx + (py - ay) * dy) / len2 : 0;
  t = Math.max(0, Math.min(1, t));
  const cx = ax + t * dx, cy = ay + t * dy;
  return Math.hypot(px - cx, py - cy);
}
