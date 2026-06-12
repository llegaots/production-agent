import "server-only";
import type { SupabaseClient } from "@supabase/supabase-js";
import type { LatLng } from "@/lib/types";
import {
  buildingsAround,
  googleAddressForFootprint,
  googleForward,
  houseNumber,
  osmAddress,
} from "./parcel";
import { haversine, pointInPolygon } from "./util";

/** Beyond this edge distance no footprint claims the pin. */
const MAX_MATCH_DISTANCE_M = 45;
/** Two addresses whose forward-geocoded points are this close are duplicate
 *  records for the same physical home, not a real conflict. */
const ALIAS_DISTANCE_M = 20;

/** Independent accuracy cross-check for a freshly opened door, run in
 *  `after()` so it never blocks the response. Building-footprint geometry and
 *  the geocoder fail differently (offset address points vs missing polygons),
 *  so their agreement is strong evidence and their disagreement is the exact
 *  signal worth flagging:
 *  - pin INSIDE the footprint and both methods name the same home (directly or
 *    as duplicate-record aliases): upgrade address_confidence to 'rooftop'.
 *  - genuinely different homes: downgrade to 'gps-only' so the CRM's
 *    needs-address-check view surfaces it. The address itself is kept.
 *  Failures (Overpass down, no key) are silent: this only ever adjusts trust. */
export async function footprintCheck(
  db: SupabaseClient,
  doorId: string,
  pin: LatLng,
  storedAddress: string | null,
): Promise<void> {
  try {
    if (!storedAddress) return;
    const buildings = await buildingsAround(pin);
    const best = buildings[0];
    if (!best || best.distanceM > MAX_MATCH_DISTANCE_M) return;

    const footprintAddress =
      osmAddress(best.tags) ??
      (await googleAddressForFootprint(best.ring, best.centroid))?.address ??
      null;
    if (!footprintAddress) return;

    const a = houseNumber(footprintAddress);
    const b = houseNumber(storedAddress);
    if (!a || !b) return;

    let sameHome = a === b;
    if (!sameHome) {
      const [pa, pb] = await Promise.all([
        googleForward(footprintAddress),
        googleForward(storedAddress),
      ]);
      sameHome =
        !!pa &&
        !!pb &&
        (haversine(pa, pb) <= ALIAS_DISTANCE_M ||
          (pointInPolygon(pa, [best.ring]) && pointInPolygon(pb, [best.ring])));
    }

    if (sameHome) {
      if (best.inside) {
        await db
          .from("D2D_DoorEvents")
          .update({ address_confidence: "rooftop" })
          .eq("id", doorId);
      }
    } else {
      await db
        .from("D2D_DoorEvents")
        .update({ address_confidence: "gps-only" })
        .eq("id", doorId);
    }
  } catch {
    // best-effort: trust adjustment only, never an error source
  }
}
