"use client";

import { cn } from "@/lib/utils";
import { VectorMap } from "./vector-map";
import { GoogleFieldMap } from "./google-field-map";
import type { DoorPing, LatLng } from "@/lib/types";

export interface FieldMapProps {
  center: LatLng;
  path?: LatLng[];
  /** the rep's actual walked GPS trail (live view) */
  breadcrumb?: LatLng[];
  trail?: DoorPing[];
  live?: LatLng | null;
  liveLabel?: string;
  progress?: number;
  mode?: "route" | "coverage";
  /** draw the planned `path` as a muted grey baseline (live view) */
  mutePath?: boolean;
  /** false → static preview (clicks pass through, no pan/zoom) */
  interactive?: boolean;
  className?: string;
}

export function FieldMap({
  center,
  path,
  breadcrumb,
  trail,
  live,
  liveLabel,
  progress = 1,
  mode = "route",
  mutePath,
  interactive = true,
  className,
}: FieldMapProps) {
  const apiKey = process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY;

  if (apiKey) {
    return (
      <div className={cn("overflow-hidden rounded-3xl", className)}>
        <GoogleFieldMap
          apiKey={apiKey}
          center={center}
          path={path}
          breadcrumb={breadcrumb}
          trail={trail}
          live={live}
          mutePath={mutePath}
          interactive={interactive}
        />
      </div>
    );
  }

  return (
    <VectorMap
      path={path}
      trail={trail}
      live={live}
      liveLabel={liveLabel}
      progress={progress}
      mode={mode}
      className={cn("h-full w-full", className)}
    />
  );
}
