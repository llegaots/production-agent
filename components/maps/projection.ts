import type { LatLng } from "@/lib/types";

export interface Projector {
  toXY: (p: LatLng) => { x: number; y: number };
  width: number;
  height: number;
}

/** Build a lat/lng → SVG-space projector that fits all points with padding. */
export function makeProjector(
  points: LatLng[],
  width: number,
  height: number,
  padding = 36,
): Projector {
  const lats = points.map((p) => p.lat);
  const lngs = points.map((p) => p.lng);
  let minLat = Math.min(...lats);
  let maxLat = Math.max(...lats);
  let minLng = Math.min(...lngs);
  let maxLng = Math.max(...lngs);

  // guard against zero span
  const latSpan = maxLat - minLat || 0.01;
  const lngSpan = maxLng - minLng || 0.01;
  minLat -= latSpan * 0.08;
  maxLat += latSpan * 0.08;
  minLng -= lngSpan * 0.08;
  maxLng += lngSpan * 0.08;

  const innerW = width - padding * 2;
  const innerH = height - padding * 2;

  return {
    width,
    height,
    toXY: (p: LatLng) => {
      const x = padding + ((p.lng - minLng) / (maxLng - minLng)) * innerW;
      // invert lat so north is up
      const y = padding + (1 - (p.lat - minLat) / (maxLat - minLat)) * innerH;
      return { x, y };
    },
  };
}
