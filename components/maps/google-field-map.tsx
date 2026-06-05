"use client";

import { useEffect } from "react";
import { APIProvider, Map, useMap } from "@vis.gl/react-google-maps";
import type { DoorOutcome, DoorPing, LatLng } from "@/lib/types";

const outcomeColor: Record<DoorOutcome, string> = {
  lead: "#059e6e",
  answered: "#34d399",
  callback: "#f5a623",
  "not-interested": "#fb7185",
  "no-answer": "#cbd3cf",
};

const outcomeLabel: Record<DoorOutcome, string> = {
  lead: "Lead",
  answered: "Answered",
  callback: "Callback",
  "not-interested": "Not interested",
  "no-answer": "No answer",
};

const escapeHtml = (s: string) =>
  s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);

const mapStyles: google.maps.MapTypeStyle[] = [
  { elementType: "geometry", stylers: [{ color: "#eef3f0" }] },
  { elementType: "labels.text.fill", stylers: [{ color: "#6c7a73" }] },
  { elementType: "labels.text.stroke", stylers: [{ color: "#ffffff" }] },
  { featureType: "road", elementType: "geometry", stylers: [{ color: "#ffffff" }] },
  { featureType: "water", elementType: "geometry", stylers: [{ color: "#d8e8e0" }] },
  { featureType: "poi", stylers: [{ visibility: "off" }] },
  { featureType: "transit", stylers: [{ visibility: "off" }] },
];

function Layers({ path, trail, live }: { path?: LatLng[]; trail?: DoorPing[]; live?: LatLng | null }) {
  const map = useMap();

  useEffect(() => {
    if (!map) return;
    const objects: { setMap: (m: google.maps.Map | null) => void }[] = [];
    const bounds = new google.maps.LatLngBounds();

    if (path && path.length > 1) {
      objects.push(
        new google.maps.Polyline({
          path,
          geodesic: true,
          strokeColor: "#059e6e",
          strokeOpacity: 0.9,
          strokeWeight: 4,
          map,
          icons: [
            {
              icon: {
                path: google.maps.SymbolPath.FORWARD_CLOSED_ARROW,
                scale: 2.6,
                strokeColor: "#047857",
                fillColor: "#047857",
                fillOpacity: 1,
              },
              offset: "0",
              repeat: "130px", // direction arrows along the walk order
            },
          ],
        }),
      );
      path.forEach((p) => bounds.extend(p));
      const last = path[path.length - 1];
      const sameEnds =
        Math.abs(path[0].lat - last.lat) < 1e-6 && Math.abs(path[0].lng - last.lng) < 1e-6;
      // START marker
      objects.push(
        new google.maps.Marker({
          position: path[0],
          map,
          title: sameEnds ? "Start / End (meet point)" : "Start (meet point)",
          zIndex: 999,
          label: { text: "S", color: "#ffffff", fontSize: "11px", fontWeight: "700" },
          icon: {
            path: google.maps.SymbolPath.CIRCLE,
            scale: 11,
            fillColor: "#059e6e",
            fillOpacity: 1,
            strokeColor: "#ffffff",
            strokeWeight: 2.5,
          },
        }),
      );
      // END marker (open route ends elsewhere)
      if (!sameEnds) {
        objects.push(
          new google.maps.Marker({
            position: last,
            map,
            title: "End",
            zIndex: 999,
            label: { text: "E", color: "#ffffff", fontSize: "11px", fontWeight: "700" },
            icon: {
              path: google.maps.SymbolPath.CIRCLE,
              scale: 11,
              fillColor: "#0d1713",
              fillOpacity: 1,
              strokeColor: "#ffffff",
              strokeWeight: 2.5,
            },
          }),
        );
      }
    }

    const info = new google.maps.InfoWindow();
    trail?.forEach((t) => {
      const circle = new google.maps.Circle({
        center: t.position,
        radius: 14,
        map,
        fillColor: outcomeColor[t.outcome],
        fillOpacity: 1,
        strokeColor: "#ffffff",
        strokeWeight: 2,
        clickable: true,
      });
      const content =
        `<div style="font:700 12px system-ui;color:#0d1713">${outcomeLabel[t.outcome]}</div>` +
        (t.note
          ? `<div style="font:12px/1.4 system-ui;color:#52605a;max-width:220px;margin-top:2px">${escapeHtml(t.note)}</div>`
          : "");
      const open = () => {
        info.setContent(content);
        info.setPosition(t.position);
        info.open(map);
      };
      circle.addListener("mouseover", open);
      circle.addListener("click", open);
      circle.addListener("mouseout", () => info.close());
      objects.push(circle);
      bounds.extend(t.position);
    });

    if (live) {
      objects.push(
        new google.maps.Circle({
          center: live,
          radius: 20,
          map,
          fillColor: "#059e6e",
          fillOpacity: 1,
          strokeColor: "#ffffff",
          strokeWeight: 3,
        }),
      );
      bounds.extend(live);
    }

    if (!bounds.isEmpty()) map.fitBounds(bounds, 56);

    return () => {
      objects.forEach((o) => o.setMap(null));
      info.close();
    };
  }, [map, path, trail, live]);

  return null;
}

export function GoogleFieldMap({
  apiKey,
  center,
  path,
  trail,
  live,
}: {
  apiKey: string;
  center: LatLng;
  path?: LatLng[];
  trail?: DoorPing[];
  live?: LatLng | null;
}) {
  return (
    <APIProvider apiKey={apiKey}>
      <Map
        defaultCenter={center}
        defaultZoom={15}
        disableDefaultUI
        gestureHandling="greedy"
        styles={mapStyles}
        className="h-full w-full"
      >
        <Layers path={path} trail={trail} live={live} />
      </Map>
    </APIProvider>
  );
}
