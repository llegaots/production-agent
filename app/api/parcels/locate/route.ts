import type { NextRequest } from "next/server";
import {
  buildingsAround,
  googleAddressForFootprint,
  googleForward,
  googleReverse,
  houseNumber,
  osmAddress,
  type ParcelLocateResponse,
  type ParcelMatch,
} from "@/lib/geo/parcel";
import { reverseGeocodeDetailed } from "@/lib/geo/geocode";
import { haversine, pointInPolygon } from "@/lib/geo/util";

export const runtime = "nodejs";
export const maxDuration = 30;

/** Beyond this edge distance no footprint claims the pin (a rep would never
 *  dwell this far from the home they are knocking). */
const MAX_MATCH_DISTANCE_M = 45;

/** Two addresses whose forward-geocoded points are this close are duplicate
 *  records for the same physical home, not a real conflict. */
const ALIAS_DISTANCE_M = 20;

/** Resolve one dropped pin two independent ways, side by side:
 *  1. parcel: building-footprint point-in-polygon (geometry)
 *  2. google: Google rooftop reverse geocode of the pin (address points)
 *  Then judge whether they name the same home. Used by the Parcel Lab page. */
export async function GET(req: NextRequest) {
  const lat = Number(req.nextUrl.searchParams.get("lat"));
  const lng = Number(req.nextUrl.searchParams.get("lng"));
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
    return Response.json({ error: "lat and lng are required numbers" }, { status: 400 });
  }
  const pin = { lat, lng };

  // The two lookups are independent: run them concurrently.
  const [footprints, google] = await Promise.all([
    buildingsAround(pin)
      .then((b) => ({ buildings: b, error: null as string | null }))
      .catch((e) => ({ buildings: [], error: e instanceof Error ? e.message : String(e) })),
    googleReverse(pin),
  ]);

  // Pick the footprint the pin is inside (distance 0 sorts first), else the
  // closest one within the claim radius.
  let parcel: ParcelMatch | null = null;
  const best = footprints.buildings[0];
  if (best && best.distanceM <= MAX_MATCH_DISTANCE_M) {
    let address = osmAddress(best.tags);
    let addressSource: ParcelMatch["addressSource"] = address ? "osm" : null;
    if (!address) {
      const g = await googleAddressForFootprint(best.ring, best.centroid);
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

  // Verdict: same house number is agreement. Different numbers might still be
  // one home with duplicate municipal records, so forward-geocode both and
  // compare where they land before calling it a conflict.
  let verdict: ParcelLocateResponse["verdict"] = null;
  if (parcel?.address && google?.address) {
    const a = houseNumber(parcel.address);
    const b = houseNumber(google.address);
    if (!a || !b || a === b) {
      verdict = "agree";
    } else {
      const [pa, pb] = await Promise.all([
        googleForward(parcel.address),
        googleForward(google.address),
      ]);
      const ring = parcel.ring;
      const sameHome =
        !!pa &&
        !!pb &&
        (haversine(pa, pb) <= ALIAS_DISTANCE_M ||
          (pointInPolygon(pa, [ring]) && pointInPolygon(pb, [ring])));
      verdict = sameHome ? "alias" : "conflict";
    }
  }

  const response: ParcelLocateResponse = {
    pin,
    parcel,
    google,
    verdict,
    parcelError: footprints.error,
  };
  return Response.json(response);
}
