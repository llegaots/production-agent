/* ----------------------------------------------------------------------------
   Browser GPS dwell tracker. Watches the rep's position and detects "doors" —
   when they stop moving for a bit, that's a house they walked up to. Emits a
   door-open when a dwell begins and a door-close when they move on, so the
   caller can attach the transcript captured between those points.

   GPS in residential areas drifts ~5–20m, so the thresholds are deliberately
   forgiving; pins land near the right house, not surveyor-accurate.
---------------------------------------------------------------------------- */

const STATIONARY_RADIUS_M = 16; // within this of the anchor = "not moving"
const DWELL_MS = 18_000; // stationary this long → a door visit begins
const MOVE_AWAY_M = 28; // moved this far from the door → visit ends
const MAX_ACCURACY_M = 60; // ignore very noisy fixes

export interface DoorVisit {
  lat: number;
  lng: number;
  startedAt: string;
  endedAt: string;
}

export interface DwellOptions {
  onPosition?: (lat: number, lng: number, accuracy: number) => void;
  onDoorOpen?: () => void;
  onDoorClose?: (door: DoorVisit) => void;
  onError?: (message: string) => void;
}

function metersBetween(aLat: number, aLng: number, bLat: number, bLng: number): number {
  const R = 6371000;
  const dLat = ((bLat - aLat) * Math.PI) / 180;
  const dLng = ((bLng - aLng) * Math.PI) / 180;
  const la1 = (aLat * Math.PI) / 180;
  const la2 = (bLat * Math.PI) / 180;
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(la1) * Math.cos(la2) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}

export class DwellTracker {
  private opts: DwellOptions;
  private watchId: number | null = null;
  private anchor: { lat: number; lng: number } | null = null;
  private anchorSince = 0;
  private doorOpen = false;
  private doorAnchor: { lat: number; lng: number } | null = null;
  private doorStartedAt = "";
  private paused = false;

  constructor(opts: DwellOptions) {
    this.opts = opts;
  }

  start(): void {
    if (!("geolocation" in navigator)) {
      this.opts.onError?.("This device has no GPS / location support.");
      return;
    }
    this.watchId = navigator.geolocation.watchPosition(
      (pos) => this.onFix(pos),
      (err) => this.opts.onError?.(err.message || "Location permission denied."),
      { enableHighAccuracy: true, maximumAge: 4000, timeout: 15000 },
    );
  }

  setPaused(paused: boolean): void {
    this.paused = paused;
  }

  /** Close any door currently open (call when the session ends). */
  flush(): void {
    if (this.doorOpen && this.doorAnchor) {
      this.opts.onDoorClose?.({
        lat: this.doorAnchor.lat,
        lng: this.doorAnchor.lng,
        startedAt: this.doorStartedAt,
        endedAt: new Date().toISOString(),
      });
      this.doorOpen = false;
    }
  }

  stop(): void {
    this.flush();
    if (this.watchId !== null) navigator.geolocation.clearWatch(this.watchId);
    this.watchId = null;
  }

  private onFix(pos: GeolocationPosition): void {
    if (this.paused) return;
    const { latitude: lat, longitude: lng, accuracy } = pos.coords;
    if (accuracy && accuracy > MAX_ACCURACY_M) return; // too noisy to trust
    this.opts.onPosition?.(lat, lng, accuracy ?? 0);

    const now = Date.now();
    if (!this.anchor) {
      this.anchor = { lat, lng };
      this.anchorSince = now;
      return;
    }

    const fromAnchor = metersBetween(this.anchor.lat, this.anchor.lng, lat, lng);

    if (fromAnchor <= STATIONARY_RADIUS_M) {
      // Still parked near the anchor — open a door once we've dwelled long enough.
      if (!this.doorOpen && now - this.anchorSince >= DWELL_MS) {
        this.doorOpen = true;
        this.doorAnchor = { ...this.anchor };
        this.doorStartedAt = new Date(this.anchorSince).toISOString();
        this.opts.onDoorOpen?.();
      }
      return;
    }

    // Moved. If a door was open and we've walked away, close it.
    if (this.doorOpen && this.doorAnchor) {
      const fromDoor = metersBetween(this.doorAnchor.lat, this.doorAnchor.lng, lat, lng);
      if (fromDoor > MOVE_AWAY_M) {
        this.opts.onDoorClose?.({
          lat: this.doorAnchor.lat,
          lng: this.doorAnchor.lng,
          startedAt: this.doorStartedAt,
          endedAt: new Date().toISOString(),
        });
        this.doorOpen = false;
        this.doorAnchor = null;
      } else {
        // drifted but still within the door's radius — keep the visit open
        return;
      }
    }

    // Re-anchor at the new spot.
    this.anchor = { lat, lng };
    this.anchorSince = now;
  }
}
