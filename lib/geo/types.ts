import type { LatLng } from "@/lib/types";

export interface GeoBounds {
  minLat: number;
  minLng: number;
  maxLat: number;
  maxLng: number;
}

/** An ordered polyline for one street (an OSM "way"). */
export interface StreetSegment {
  id: string;
  name?: string;
  points: LatLng[];
}

export interface GeocodeResult {
  displayName: string;
  center: LatLng;
  bounds: GeoBounds;
  /** Outer ring(s) of the area's real boundary (a postal-code/FSA polygon),
   *  when OSM has one — used to clip coverage to inside the area. */
  polygon?: LatLng[][];
}
