/* ----------------------------------------------------------------------------
   Browser GPS dwell tracker. Watches the rep's position and detects "doors" -
   when they stop moving for a bit, that's a house they walked up to. Emits a
   door-open when a dwell begins and a door-close when they move on, so the
   caller can attach the transcript captured between those points.

   GPS in residential areas drifts ~5-20m, so the thresholds are deliberately
   forgiving; pins land near the right house, not surveyor-accurate.
---------------------------------------------------------------------------- */

const STATIONARY_RADIUS_M = 16; // within this of the anchor = "not moving"
const DWELL_MS = 18_000; // stationary this long → a door visit begins
const MOVE_AWAY_M = 28; // moved this far from the door → visit ends
const MAX_ACCURACY_M = 60; // ignore very noisy fixes

export interface DoorVisit {
  lat: number;
  lng: number;
  /** reported accuracy (meters) of the chosen fix - lower is better */
  accuracyM?: number;
  startedAt: string;
  endedAt: string;
}

export interface DoorOpenFix {
  lat: number;
  lng: number;
  accuracyM?: number;
  startedAt: string;
}

export interface DwellOptions {
  onPosition?: (lat: number, lng: number, accuracy: number) => void;
  /** fires the moment a dwell begins, with the best fix gathered so far - the
   *  caller can resolve the home's address while the rep is still standing there */
  onDoorOpen?: (open: DoorOpenFix) => void;
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

type Fix = { lat: number; lng: number; acc: number };

/** Best position from a set of stationary fixes: the median of the most-accurate
 *  half (robust to GPS drift and outliers), reported with the tightest accuracy. */
function bestFix(fixes: Fix[]): Fix | null {
  if (!fixes.length) return null;
  const sorted = [...fixes].sort((a, b) => a.acc - b.acc);
  const keep = sorted.slice(0, Math.max(1, Math.ceil(sorted.length / 2)));
  const median = (vals: number[]) => {
    const s = [...vals].sort((a, b) => a - b);
    const m = Math.floor(s.length / 2);
    return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
  };
  return { lat: median(keep.map((f) => f.lat)), lng: median(keep.map((f) => f.lng)), acc: keep[0].acc };
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
  /** GPS fixes gathered while parked at the current spot - we keep the best one */
  private dwellFixes: Fix[] = [];

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
    this.emitDoorClose();
  }

  /** Emit the open door's visit using the best of the fixes gathered while parked. */
  private emitDoorClose(): void {
    if (!this.doorOpen || !this.doorAnchor) return;
    const best = bestFix(this.dwellFixes) ?? { lat: this.doorAnchor.lat, lng: this.doorAnchor.lng, acc: 0 };
    this.opts.onDoorClose?.({
      lat: best.lat,
      lng: best.lng,
      accuracyM: best.acc,
      startedAt: this.doorStartedAt,
      endedAt: new Date().toISOString(),
    });
    this.doorOpen = false;
    this.doorAnchor = null;
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
    const acc = accuracy ?? MAX_ACCURACY_M;
    this.opts.onPosition?.(lat, lng, acc);

    const now = Date.now();
    if (!this.anchor) {
      this.anchor = { lat, lng };
      this.anchorSince = now;
      this.dwellFixes = [{ lat, lng, acc }];
      return;
    }

    const fromAnchor = metersBetween(this.anchor.lat, this.anchor.lng, lat, lng);

    if (fromAnchor <= STATIONARY_RADIUS_M) {
      // Still parked near the anchor - collect fixes so we can pick the best one,
      // and open a door once we've dwelled long enough.
      this.dwellFixes.push({ lat, lng, acc });
      if (this.dwellFixes.length > 80) this.dwellFixes.shift();
      if (!this.doorOpen && now - this.anchorSince >= DWELL_MS) {
        this.doorOpen = true;
        this.doorAnchor = { ...this.anchor };
        this.doorStartedAt = new Date(this.anchorSince).toISOString();
        const best = bestFix(this.dwellFixes) ?? { lat: this.anchor.lat, lng: this.anchor.lng, acc: 0 };
        this.opts.onDoorOpen?.({
          lat: best.lat,
          lng: best.lng,
          accuracyM: best.acc,
          startedAt: this.doorStartedAt,
        });
      }
      return;
    }

    // Moved. If a door was open and we've walked away, close it (best fix wins).
    if (this.doorOpen && this.doorAnchor) {
      const fromDoor = metersBetween(this.doorAnchor.lat, this.doorAnchor.lng, lat, lng);
      if (fromDoor > MOVE_AWAY_M) {
        this.emitDoorClose();
      } else {
        // drifted but still within the door's radius - keep the visit open
        return;
      }
    }

    // Re-anchor at the new spot, starting a fresh fix buffer.
    this.anchor = { lat, lng };
    this.anchorSince = now;
    this.dwellFixes = [{ lat, lng, acc }];
  }
}
