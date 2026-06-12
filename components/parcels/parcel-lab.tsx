"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { APIProvider, Map, useMap, type MapMouseEvent } from "@vis.gl/react-google-maps";
import { LocateFixed, Layers, MousePointerClick, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { LatLng } from "@/lib/types";
import type { ParcelLocateResponse } from "@/lib/geo/parcel";

const mapStyles: google.maps.MapTypeStyle[] = [
  { elementType: "geometry", stylers: [{ color: "#eef3f0" }] },
  { elementType: "labels.text.fill", stylers: [{ color: "#6c7a73" }] },
  { elementType: "labels.text.stroke", stylers: [{ color: "#ffffff" }] },
  { featureType: "road", elementType: "geometry", stylers: [{ color: "#ffffff" }] },
  { featureType: "water", elementType: "geometry", stylers: [{ color: "#d8e8e0" }] },
  { featureType: "poi", stylers: [{ visibility: "off" }] },
  { featureType: "transit", stylers: [{ visibility: "off" }] },
];

const DEFAULT_CENTER: LatLng = { lat: 45.4275, lng: -73.8651 };

/** First house number in an address string, for the agree/disagree banner. */
function houseNumber(address: string | null | undefined): string | null {
  if (!address) return null;
  const m = address.match(/\d+/);
  return m ? m[0] : null;
}

/* Imperative overlays: dropped pin, candidate footprints (white), the matched
   footprint (green), and where today's pipeline would snap the pin (amber).
   Rebuilt per result, same pattern as the other map layers in the app. */
function Overlays({ pin, result }: { pin: LatLng | null; result: ParcelLocateResponse | null }) {
  const map = useMap();
  const objects = useRef<{ setMap: (m: google.maps.Map | null) => void }[]>([]);

  useEffect(() => {
    if (!map) return;
    objects.current.forEach((o) => o.setMap(null));
    objects.current = [];

    if (pin) {
      objects.current.push(
        new google.maps.Marker({ position: pin, map, zIndex: 60, title: "Dropped pin" }),
      );
    }
    if (result) {
      result.candidates.forEach((c) => {
        if (result.parcel && c.ring === result.parcel.ring) return;
        objects.current.push(
          new google.maps.Polygon({
            paths: c.ring,
            map,
            strokeColor: "#ffffff",
            strokeOpacity: 0.8,
            strokeWeight: 1.2,
            fillColor: "#ffffff",
            fillOpacity: 0.06,
            clickable: false,
            zIndex: 10,
          }),
        );
      });
      if (result.parcel) {
        objects.current.push(
          new google.maps.Polygon({
            paths: result.parcel.ring,
            map,
            strokeColor: "#10b981",
            strokeOpacity: 1,
            strokeWeight: 3,
            fillColor: "#10b981",
            fillOpacity: 0.25,
            clickable: false,
            zIndex: 20,
          }),
        );
      }
      if (result.current?.snapped) {
        objects.current.push(
          new google.maps.Marker({
            position: result.current.snapped,
            map,
            zIndex: 50,
            title: "Where today's pipeline snaps the pin",
            icon: {
              path: google.maps.SymbolPath.CIRCLE,
              scale: 7,
              fillColor: "#f59e0b",
              fillOpacity: 1,
              strokeColor: "#ffffff",
              strokeWeight: 2,
            },
          }),
        );
      }
    }
  }, [map, pin, result]);

  useEffect(
    () => () => {
      objects.current.forEach((o) => o.setMap(null));
      objects.current = [];
    },
    [],
  );

  return null;
}

/** Pans the camera to the browser's location once, so the user can test the
 *  homes around them. Falls back silently to the default center. */
function GeolocateButton() {
  const map = useMap();
  const goToMe = useCallback(() => {
    if (!map || !navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        map.panTo({ lat: pos.coords.latitude, lng: pos.coords.longitude });
        map.setZoom(19);
      },
      () => {},
      { enableHighAccuracy: true, timeout: 8000 },
    );
  }, [map]);

  return (
    <button
      onClick={goToMe}
      className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[12px] font-semibold text-ink-soft shadow-soft transition-colors hover:bg-surface-muted"
    >
      <LocateFixed className="size-3.5" /> My location
    </button>
  );
}

function MethodRow({
  label,
  tone,
  address,
  meta,
  sub,
}: {
  label: string;
  tone: "green" | "blue" | "amber";
  address: string | null;
  meta?: string | null;
  sub?: string | null;
}) {
  const dot = { green: "bg-emerald-500", blue: "bg-sky-500", amber: "bg-amber-500" }[tone];
  return (
    <div className="rounded-xl border border-line bg-surface p-3">
      <div className="flex items-center gap-2">
        <span className={cn("size-2 rounded-full", dot)} />
        <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">{label}</span>
      </div>
      <div className="mt-1.5 text-[14px] font-semibold leading-snug text-ink">
        {address ?? "No address resolved"}
      </div>
      {meta && <div className="mt-0.5 text-[12px] text-ink-soft">{meta}</div>}
      {sub && <div className="mt-0.5 text-[11px] text-muted">{sub}</div>}
    </div>
  );
}

export function ParcelLab() {
  const apiKey = process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY;
  const [pin, setPin] = useState<LatLng | null>(null);
  const [result, setResult] = useState<ParcelLocateResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [satellite, setSatellite] = useState(true);
  const seq = useRef(0);

  const locate = useCallback(async (p: LatLng) => {
    const mySeq = ++seq.current;
    setPin(p);
    setResult(null);
    setError(null);
    setLoading(true);
    try {
      const res = await fetch(`/api/parcels/locate?lat=${p.lat}&lng=${p.lng}`);
      const json = (await res.json()) as ParcelLocateResponse & { error?: string };
      if (mySeq !== seq.current) return; // a newer pin superseded this one
      if (!res.ok) throw new Error(json.error ?? `Lookup failed (HTTP ${res.status})`);
      setResult(json);
    } catch (e) {
      if (mySeq === seq.current) setError(e instanceof Error ? e.message : "Lookup failed");
    } finally {
      if (mySeq === seq.current) setLoading(false);
    }
  }, []);

  const onMapClick = useCallback(
    (e: MapMouseEvent) => {
      const ll = e.detail.latLng;
      if (ll) void locate({ lat: ll.lat, lng: ll.lng });
    },
    [locate],
  );

  if (!apiKey) {
    return (
      <div className="grid h-[480px] place-items-center rounded-2xl border border-line bg-surface-muted text-[13px] text-muted">
        Add NEXT_PUBLIC_GOOGLE_MAPS_API_KEY to use the Parcel Lab.
      </div>
    );
  }

  const parcelNum = houseNumber(result?.parcel?.address);
  const currentNum = houseNumber(result?.current?.address);
  const verdict =
    result && parcelNum && currentNum ? (parcelNum === currentNum ? "agree" : "disagree") : null;

  return (
    <div className="flex flex-col gap-4 xl:flex-row">
      <div className="relative h-[420px] flex-1 overflow-hidden rounded-2xl border border-line shadow-soft xl:h-[600px]">
        <APIProvider apiKey={apiKey}>
          <Map
            defaultCenter={DEFAULT_CENTER}
            defaultZoom={18}
            mapTypeId={satellite ? "hybrid" : "roadmap"}
            styles={satellite ? undefined : mapStyles}
            disableDefaultUI
            gestureHandling="greedy"
            clickableIcons={false}
            onClick={onMapClick}
            className="h-full w-full"
          >
            <Overlays pin={pin} result={result} />
            <div className="absolute left-3 top-3 z-10 flex items-center gap-2">
              <GeolocateButton />
              <button
                onClick={() => setSatellite((s) => !s)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[12px] font-semibold text-ink-soft shadow-soft transition-colors hover:bg-surface-muted"
              >
                <Layers className="size-3.5" /> {satellite ? "Map view" : "Satellite"}
              </button>
            </div>
          </Map>
        </APIProvider>
        {!pin && (
          <div className="pointer-events-none absolute inset-x-0 bottom-4 z-10 flex justify-center">
            <span className="inline-flex items-center gap-2 rounded-full bg-ink/85 px-3.5 py-2 text-[12px] font-semibold text-white shadow-soft">
              <MousePointerClick className="size-4" /> Click any rooftop or driveway to drop a pin
            </span>
          </div>
        )}
      </div>

      <div className="flex w-full flex-col gap-3 xl:w-[360px]">
        {loading && (
          <div className="flex items-center gap-2 rounded-xl border border-line bg-surface p-3 text-[13px] text-ink-soft">
            <Loader2 className="size-4 animate-spin" /> Resolving address three ways...
          </div>
        )}
        {error && (
          <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-[13px] text-rose-700">
            {error}
          </div>
        )}
        {verdict && (
          <div
            className={cn(
              "rounded-xl p-3 text-[13px] font-semibold",
              verdict === "agree"
                ? "border border-emerald-200 bg-emerald-50 text-emerald-700"
                : "border border-rose-200 bg-rose-50 text-rose-700",
            )}
          >
            {verdict === "agree"
              ? "All methods agree on the house number."
              : "Methods disagree: today's pipeline would record a DIFFERENT house than the parcel match."}
          </div>
        )}
        {result && (
          <>
            <MethodRow
              label="Parcel match (proposed)"
              tone="green"
              address={result.parcel?.address ?? null}
              meta={
                result.parcel
                  ? result.parcel.inside
                    ? "Pin is inside this building's footprint."
                    : `Nearest footprint, ${result.parcel.distanceM} m from the pin.`
                  : result.parcelError
                    ? `Footprint source unavailable: ${result.parcelError}`
                    : "No building footprint within 45 m of the pin."
              }
              sub={
                result.parcel?.addressSource === "osm"
                  ? "Address from the building's own map data."
                  : result.parcel?.addressSource === "google"
                    ? "Address via Google rooftop lookup at the footprint."
                    : result.parcel?.addressSource === "nominatim"
                      ? "Address via Nominatim at the footprint."
                      : null
              }
            />
            <MethodRow
              label="Google rooftop (pin as-is)"
              tone="blue"
              address={result.google?.address ?? null}
              meta={
                result.google
                  ? result.google.locationType === "ROOFTOP"
                    ? "Rooftop precision."
                    : `Precision: ${result.google.locationType.toLowerCase().replace(/_/g, " ")}.`
                  : "Google Geocoding API key not configured or no result."
              }
            />
            <MethodRow
              label="Today's pipeline (Nominatim + 60 m snap)"
              tone="amber"
              address={result.current?.address ?? null}
              meta={
                result.current
                  ? result.current.snapped
                    ? `Pin snapped ${result.current.snapDistanceM} m to the amber dot.`
                    : "No snap within 60 m, raw GPS kept."
                  : "Nominatim returned nothing for this point."
              }
              sub={
                result.current
                  ? result.current.exact
                    ? "Resolved to an exact house number."
                    : "Street-level only: no house number resolved."
                  : null
              }
            />
          </>
        )}
        {!result && !loading && !error && (
          <div className="rounded-xl border border-dashed border-line bg-surface-muted p-4 text-[13px] leading-relaxed text-muted">
            Drop a pin where a rep would actually stand (a porch, a driveway, the
            sidewalk in front of a house). The green polygon is the building the
            parcel method picks, the amber dot is where today's pipeline would
            snap the pin. Compare the addresses side by side.
          </div>
        )}
      </div>
    </div>
  );
}
