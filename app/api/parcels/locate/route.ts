import type { NextRequest } from "next/server";
import {
  buildingsAround,
  googleReverse,
  osmAddress,
  type ParcelLocateResponse,
  type ParcelMatch,
} from "@/lib/geo/parcel";
import { reverseGeocodeDetailed } from "@/lib/geo/geocode";
import { haversine } from "@/lib/geo/util";

export const runtime = "nodejs";
export const maxDuration = 30;

/** Beyond this edge distance no footprint claims the pin (a rep would never
 *  dwell this far from the home they are knocking). */
const MAX_MATCH_DISTANCE_M = 45;

/** Resolve one dropped pin three ways, side by side:
 *  1. parcel:  building-footprint point-in-polygon (the proposed method)
 *  2. google:  plain Google rooftop reverse geocode of the pin
 *  3. current: today's pipeline (Nominatim nearest + 60 m snap)
 *  Used by the Parcel Lab page to compare address-resolution accuracy. */
export async function GET(req: NextRequest) {
  const lat = Number(req.nextUrl.searchParams.get("lat"));
  const lng = Number(req.nextUrl.searchParams.get("lng"));
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
    return Response.json({ error: "lat and lng are required numbers" }, { status: 400 });
  }
  const pin = { lat, lng };

  // The three lookups are independent: run them concurrently.
  const [footprints, google, current] = await Promise.all([
    buildingsAround(pin)
      .then((b) => ({ buildings: b, error: null as string | null }))
      .catch((e) => ({ buildings: [], error: e instanceof Error ? e.message : String(e) })),
    googleReverse(pin),
    reverseGeocodeDetailed(lat, lng),
  ]);

  // Pick the footprint the pin is inside (distance 0 sorts first), else the
  // closest one within the claim radius.
  let parcel: ParcelMatch | null = null;
  const best = footprints.buildings[0];
  if (best && best.distanceM <= MAX_MATCH_DISTANCE_M) {
    let address = osmAddress(best.tags);
    let addressSource: ParcelMatch["addressSource"] = address ? "osm" : null;
    if (!address) {
      const g = await googleReverse(best.centroid);
      if (g) {
        address = g.address;
        addressSource = "google";
      }
    }
    if (!address) {
      const n = await reverseGeocodeDetailed(best.centroid.lat, best.centroid.lng);
      if (n?.address) {
        address = n.address;
        addressSource = "nominatim";
      }
    }
    parcel = {
      ring: best.ring,
      centroid: best.centroid,
      inside: best.inside,
      distanceM: Math.round(best.distanceM),
      address,
      addressSource,
    };
  }

  // Reproduce exactly what the doors route records today (60 m snap rule).
  const snapDistanceM = current ? haversine(pin, { lat: current.lat, lng: current.lng }) : null;
  const response: ParcelLocateResponse = {
    pin,
    parcel,
    google,
    current: current
      ? {
          address: current.address,
          exact: current.exact,
          snapped:
            snapDistanceM !== null && snapDistanceM <= 60
              ? { lat: current.lat, lng: current.lng }
              : null,
          snapDistanceM: snapDistanceM === null ? null : Math.round(snapDistanceM),
        }
      : null,
    candidates: footprints.buildings.slice(0, 40).map((b) => ({ id: b.id, ring: b.ring })),
    parcelError: footprints.error,
  };
  return Response.json(response);
}
