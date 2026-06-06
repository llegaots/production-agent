"use client";

import { useEffect, useState } from "react";

/** Current time, refreshed on an interval. Starts null so the server render and
 *  the first client render match (no hydration mismatch), then fills in right
 *  after mount. Updates run from timers, never synchronously inside the effect. */
export function useNow(intervalMs = 60_000): Date | null {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    const tick = () => setNow(new Date());
    const raf = requestAnimationFrame(tick);
    const id = setInterval(tick, intervalMs);
    return () => {
      cancelAnimationFrame(raf);
      clearInterval(id);
    };
  }, [intervalMs]);
  return now;
}
