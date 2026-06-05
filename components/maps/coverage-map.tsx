"use client";

import { useEffect } from "react";
import { APIProvider, Map, useMap } from "@vis.gl/react-google-maps";
import { cn } from "@/lib/utils";
import type { DoorPing, LatLng } from "@/lib/types";
import { escapeHtml, outcomeColor, outcomeLabel } from "./outcome";

export interface CoverageRoute {
  id: string;
  name: string;
  path: LatLng[];
  color: string;
}

const mapStyles: google.maps.MapTypeStyle[] = [
  { elementType: "geometry", stylers: [{ color: "#eef3f0" }] },
  { elementType: "labels.text.fill", stylers: [{ color: "#6c7a73" }] },
  { elementType: "labels.text.stroke", stylers: [{ color: "#ffffff" }] },
  { featureType: "road", elementType: "geometry", stylers: [{ color: "#ffffff" }] },
  { featureType: "water", elementType: "geometry", stylers: [{ color: "#d8e8e0" }] },
  { featureType: "poi", stylers: [{ visibility: "off" }] },
  { featureType: "transit", stylers: [{ visibility: "off" }] },
];

function Layers({
  routes,
  doors,
  highlightId,
}: {
  routes: CoverageRoute[];
  doors: DoorPing[];
  highlightId?: string | null;
}) {
  const map = useMap();

  useEffect(() => {
    if (!map) return;
    const objects: { setMap: (m: google.maps.Map | null) => void }[] = [];
    const bounds = new google.maps.LatLngBounds();

    routes.forEach((r) => {
      if (r.path.length < 2) return;
      const dim = highlightId ? r.id !== highlightId : false;
      objects.push(
        new google.maps.Polyline({
          path: r.path,
          geodesic: true,
          strokeColor: r.color,
          strokeOpacity: dim ? 0.25 : 0.9,
          strokeWeight: dim ? 3 : 4.5,
          zIndex: highlightId === r.id ? 50 : 1,
          map,
        }),
      );
      // start dot for each route
      objects.push(
        new google.maps.Marker({
          position: r.path[0],
          map,
          title: r.name,
          zIndex: highlightId === r.id ? 60 : 5,
          icon: {
            path: google.maps.SymbolPath.CIRCLE,
            scale: 6,
            fillColor: r.color,
            fillOpacity: dim ? 0.4 : 1,
            strokeColor: "#ffffff",
            strokeWeight: 2,
          },
        }),
      );
      r.path.forEach((p) => bounds.extend(p));
    });

    // Door outcome pins on top of the routes - small precise markers at each home.
    const info = new google.maps.InfoWindow();
    doors.forEach((d) => {
      const marker = new google.maps.Marker({
        position: d.position,
        map,
        zIndex: 30,
        icon: {
          path: google.maps.SymbolPath.CIRCLE,
          scale: 5.5,
          fillColor: outcomeColor[d.outcome],
          fillOpacity: 1,
          strokeColor: "#ffffff",
          strokeWeight: 1.5,
        },
      });
      const content =
        `<div style="font:700 12px system-ui;color:#0d1713">${outcomeLabel[d.outcome]}</div>` +
        (d.address ? `<div style="font:600 11px system-ui;color:#0d1713;margin-top:1px">${escapeHtml(d.address)}</div>` : "") +
        (d.note
          ? `<div style="font:12px/1.4 system-ui;color:#52605a;max-width:220px;margin-top:2px">${escapeHtml(d.note)}</div>`
          : "");
      const open = () => {
        info.setContent(content);
        info.setPosition(d.position);
        info.open(map);
      };
      marker.addListener("mouseover", open);
      marker.addListener("click", open);
      marker.addListener("mouseout", () => info.close());
      objects.push(marker);
      bounds.extend(d.position);
    });

    if (!bounds.isEmpty()) map.fitBounds(bounds, 64);
    return () => {
      objects.forEach((o) => o.setMap(null));
      info.close();
    };
  }, [map, routes, doors, highlightId]);

  return null;
}

export function CoverageMap({
  routes,
  doors = [],
  center,
  highlightId,
  className,
}: {
  routes: CoverageRoute[];
  doors?: DoorPing[];
  center: LatLng;
  highlightId?: string | null;
  className?: string;
}) {
  const apiKey = process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY;

  if (!apiKey) {
    return (
      <div className={cn("grid h-full place-items-center bg-surface-muted text-[13px] text-muted", className)}>
        Add NEXT_PUBLIC_GOOGLE_MAPS_API_KEY to see the coverage map.
      </div>
    );
  }

  return (
    <div className={cn("overflow-hidden", className)}>
      <APIProvider apiKey={apiKey}>
        <Map
          defaultCenter={center}
          defaultZoom={14}
          disableDefaultUI
          gestureHandling="greedy"
          styles={mapStyles}
          className="h-full w-full"
        >
          <Layers routes={routes} doors={doors} highlightId={highlightId} />
        </Map>
      </APIProvider>
    </div>
  );
}
