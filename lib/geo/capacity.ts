/** Time model: knocking time + walking time. Sizing is driven by REAL homes. */

export interface PaceModel {
  /** seconds per door (approach + knock + conversation, averaged) */
  timePerDoorSec: number;
  /** walking speed, meters/second */
  walkSpeedMps: number;
}

export const DEFAULT_PACE: PaceModel = {
  timePerDoorSec: 120, // 2 min/door
  walkSpeedMps: 1.25, // 4.5 km/h
};

/** Work time for an edge: knock its homes (split across the pair, one per side)
 *  + walk its length once (the pair walks together). */
export function edgeTimeSec(homes: number, lenMeters: number, m: PaceModel, people = 2): number {
  return (homes / Math.max(1, people)) * m.timePerDoorSec + lenMeters / m.walkSpeedMps;
}

/** Hours between two "HH:mm" times. */
export function shiftHours(start: string, end: string): number {
  const [sh, sm] = start.split(":").map(Number);
  const [eh, em] = end.split(":").map(Number);
  const mins = eh * 60 + em - (sh * 60 + sm);
  return Math.max(0, mins / 60);
}
