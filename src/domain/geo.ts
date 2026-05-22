import type { GeoPoint } from "./types.js";

/** Haversine distance in km between two coordinates. */
export function distanceKm(a: GeoPoint, b: GeoPoint): number {
  const R = 6371;
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const lat1 = toRad(a.lat);
  const lat2 = toRad(b.lat);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

function toRad(deg: number): number {
  return (deg * Math.PI) / 180;
}

/** Rough urban drive time at ~40 km/h average. */
export function estimateDriveMinutes(a: GeoPoint, b: GeoPoint): number {
  const km = distanceKm(a, b);
  return Math.max(5, Math.round((km / 40) * 60));
}
