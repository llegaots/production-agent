"use client";

import { useEffect, useRef } from "react";
import { APIProvider, Map, useMap } from "@vis.gl/react-google-maps";
import { cn } from "@/lib/utils";
import type { DoorPing, LatLng } from "@/lib/types";
import { escapeHtml, outcomeColor, outcomeLabel } from "./outcome";

const mapStyles: google.maps.MapTypeStyle[] = [
  { elementType: "geometry", stylers: [{ color: "#eef3f0" }] },
  { elementType: "labels.text.fill", stylers: [{ color: "#6c7a73" }] },
  { elementType: "labels.text.stroke", stylers: [{ color: "#ffffff" }] },
  { featureType: "road", elementType: "geometry", stylers: [{ color: "#ffffff" }] },
  { featureType: "water", elementType: "geometry", stylers: [{ color: "#d8e8e0" }] },
  { featureType: "poi", stylers: [{ visibility: "off" }] },
  { featureType: "transit", stylers: [{ visibility: "off" }] },
];

interface LayerProps {
  path?: LatLng[];
  breadcrumb?: LatLng[];
  trail?: DoorPing[];
  live?: LatLng | null;
  /** draw the planned `path` as a muted grey baseline (live view) */
  mutePath?: boolean;
}

function endpointMarker(map: google.maps.Map, position: LatLng, text: string, color: string, title: string) {
  return new google.maps.Marker({
    position,
    map,
    title,
    zIndex: 40,
    label: { text, color: "#ffffff", fontSize: "11px", fontWeight: "700" },
    icon: { path: google.maps.SymbolPath.CIRCLE, scale: 10, fillColor: color, fillOpacity: 1, strokeColor: "#ffffff", strokeWeight: 2.5 },
  });
}

/* Overlays are kept as persistent objects and UPDATED in place on each change
   (setPath / setPosition), instead of being torn down and rebuilt. The camera is
   fit to the geometry exactly ONCE, so the user can freely zoom/pan without it
   snapping back on the next GPS tick. */
function Layers({ path, breadcrumb, trail, live, mutePath }: LayerProps) {
  const map = useMap();
  const planned = useRef<google.maps.Polyline | null>(null);
  const endpoints = useRef<google.maps.Marker[]>([]);
  const crumb = useRef<google.maps.Polyline | null>(null);
  const startMk = useRef<google.maps.Marker | null>(null);
  const liveRing = useRef<google.maps.Marker | null>(null);
  const liveDot = useRef<google.maps.Marker | null>(null);
  const doorMks = useRef<globalThis.Map<string, google.maps.Marker>>(new globalThis.Map());
  const info = useRef<google.maps.InfoWindow | null>(null);
  const fitted = useRef(false);

  // planned route (grey baseline when live; green when planning)
  useEffect(() => {
    if (!map) return;
    if (path && path.length > 1) {
      if (!planned.current) planned.current = new google.maps.Polyline({ map, geodesic: true, zIndex: 1 });
      planned.current.setOptions({
        path,
        strokeColor: mutePath ? "#c2ccc7" : "#059e6e",
        strokeOpacity: mutePath ? 1 : 0.9,
        strokeWeight: mutePath ? 6 : 4,
      });
      endpoints.current.forEach((m) => m.setMap(null));
      endpoints.current = [];
      if (!mutePath) {
        const last = path[path.length - 1];
        const same = Math.abs(path[0].lat - last.lat) < 1e-6 && Math.abs(path[0].lng - last.lng) < 1e-6;
        endpoints.current.push(endpointMarker(map, path[0], "S", "#059e6e", same ? "Start / End" : "Start"));
        if (!same) endpoints.current.push(endpointMarker(map, last, "E", "#0d1713", "End"));
      }
    } else if (planned.current) {
      planned.current.setMap(null);
      planned.current = null;
    }
  }, [map, path, mutePath]);

  // walked breadcrumb — grows by updating the same polyline's path (smooth)
  useEffect(() => {
    if (!map) return;
    if (breadcrumb && breadcrumb.length > 1) {
      if (!crumb.current)
        crumb.current = new google.maps.Polyline({ map, geodesic: true, strokeColor: "#059e6e", strokeOpacity: 1, strokeWeight: 5, zIndex: 3 });
      crumb.current.setPath(breadcrumb);
      if (!startMk.current) startMk.current = endpointMarker(map, breadcrumb[0], "S", "#059e6e", "Started here");
    } else if (crumb.current) {
      crumb.current.setMap(null);
      crumb.current = null;
      startMk.current?.setMap(null);
      startMk.current = null;
    }
  }, [map, breadcrumb]);

  // door pins — only ADD markers for newly-seen doors (existing ones stay put)
  useEffect(() => {
    if (!map) return;
    if (!info.current) info.current = new google.maps.InfoWindow();
    const seen = new Set<string>();
    (trail ?? []).forEach((t) => {
      seen.add(t.id);
      if (doorMks.current.has(t.id)) return;
      const marker = new google.maps.Marker({
        position: t.position,
        map,
        zIndex: 20,
        icon: { path: google.maps.SymbolPath.CIRCLE, scale: 6, fillColor: outcomeColor[t.outcome], fillOpacity: 1, strokeColor: "#ffffff", strokeWeight: 1.5 },
      });
      const content =
        `<div style="font:700 12px system-ui;color:#0d1713">${outcomeLabel[t.outcome]}</div>` +
        (t.address ? `<div style="font:600 11px system-ui;color:#0d1713;margin-top:1px">${escapeHtml(t.address)}</div>` : "") +
        (t.note ? `<div style="font:12px/1.4 system-ui;color:#52605a;max-width:220px;margin-top:2px">${escapeHtml(t.note)}</div>` : "");
      const open = () => {
        info.current!.setContent(content);
        info.current!.setPosition(t.position);
        info.current!.open(map);
      };
      marker.addListener("mouseover", open);
      marker.addListener("click", open);
      marker.addListener("mouseout", () => info.current!.close());
      doorMks.current.set(t.id, marker);
    });
    for (const [id, m] of doorMks.current) {
      if (!seen.has(id)) {
        m.setMap(null);
        doorMks.current.delete(id);
      }
    }
  }, [map, trail]);

  // live position — move the same dot (no flicker)
  useEffect(() => {
    if (!map) return;
    if (live) {
      if (!liveRing.current)
        liveRing.current = new google.maps.Marker({ map, zIndex: 29, icon: { path: google.maps.SymbolPath.CIRCLE, scale: 13, fillColor: "#059e6e", fillOpacity: 0.22, strokeWeight: 0 } });
      if (!liveDot.current)
        liveDot.current = new google.maps.Marker({ map, zIndex: 30, icon: { path: google.maps.SymbolPath.CIRCLE, scale: 6.5, fillColor: "#059e6e", fillOpacity: 1, strokeColor: "#ffffff", strokeWeight: 2.5 } });
      liveRing.current.setPosition(live);
      liveDot.current.setPosition(live);
    } else {
      liveRing.current?.setMap(null);
      liveRing.current = null;
      liveDot.current?.setMap(null);
      liveDot.current = null;
    }
  }, [map, live]);

  // Fit the camera to the geometry exactly once, then leave it to the user. We
  // wait for REAL geometry (a route, a multi-point trace, or door pins) before
  // locking, so a lone live/placeholder point can't pin the view to the wrong
  // place and never recover.
  useEffect(() => {
    if (!map || fitted.current) return;
    const hasRoute = (path?.length ?? 0) > 1;
    const hasTrace = (breadcrumb?.length ?? 0) > 1;
    const hasDoors = (trail?.length ?? 0) > 0;
    if (!hasRoute && !hasTrace && !hasDoors) return; // wait for it to arrive

    const b = new google.maps.LatLngBounds();
    let n = 0;
    const add = (p: LatLng) => {
      b.extend(p);
      n++;
    };
    (path ?? []).forEach(add);
    (breadcrumb ?? []).forEach(add);
    (trail ?? []).forEach((t) => add(t.position));
    if (live) add(live);
    if (n === 0) return;
    fitted.current = true;
    const ne = b.getNorthEast();
    const sw = b.getSouthWest();
    const tiny = Math.abs(ne.lat() - sw.lat()) < 0.0008 && Math.abs(ne.lng() - sw.lng()) < 0.0008;
    if (tiny) {
      map.setCenter(b.getCenter());
      map.setZoom(17);
    } else {
      map.fitBounds(b, 56);
    }
  }, [map, path, breadcrumb, trail, live]);

  // tear everything down on unmount only
  useEffect(() => {
    const doors = doorMks.current;
    return () => {
      planned.current?.setMap(null);
      endpoints.current.forEach((m) => m.setMap(null));
      crumb.current?.setMap(null);
      startMk.current?.setMap(null);
      liveRing.current?.setMap(null);
      liveDot.current?.setMap(null);
      doors.forEach((m) => m.setMap(null));
      doors.clear();
      info.current?.close();
    };
  }, []);

  return null;
}

export function GoogleFieldMap({
  apiKey,
  center,
  path,
  breadcrumb,
  trail,
  live,
  mutePath,
  interactive = true,
}: {
  apiKey: string;
  center: LatLng;
  path?: LatLng[];
  breadcrumb?: LatLng[];
  trail?: DoorPing[];
  live?: LatLng | null;
  mutePath?: boolean;
  interactive?: boolean;
}) {
  return (
    <div className={cn("h-full w-full", !interactive && "pointer-events-none")}>
      <APIProvider apiKey={apiKey}>
        <Map
          defaultCenter={center}
          defaultZoom={15}
          disableDefaultUI
          gestureHandling={interactive ? "greedy" : "none"}
          clickableIcons={false}
          styles={mapStyles}
          className="h-full w-full"
        >
          <Layers path={path} breadcrumb={breadcrumb} trail={trail} live={live} mutePath={mutePath} />
        </Map>
      </APIProvider>
    </div>
  );
}
