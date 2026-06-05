"use client";

import { useEffect, useRef } from "react";
import { animate, useInView, useMotionValue } from "framer-motion";

export function AnimatedNumber({
  value,
  decimals = 0,
  duration = 1.1,
  className,
  prefix = "",
  suffix = "",
}: {
  value: number;
  decimals?: number;
  duration?: number;
  className?: string;
  prefix?: string;
  suffix?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, margin: "-8% 0px" });
  const mv = useMotionValue(0);

  useEffect(() => {
    if (!inView) return;
    const fmt = new Intl.NumberFormat("en-US", {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    });
    const controls = animate(mv, value, {
      duration,
      ease: [0.22, 1, 0.36, 1],
    });
    const unsub = mv.on("change", (v) => {
      if (ref.current) ref.current.textContent = `${prefix}${fmt.format(v)}${suffix}`;
    });
    return () => {
      controls.stop();
      unsub();
    };
  }, [inView, value, decimals, duration, prefix, suffix, mv]);

  return (
    <span ref={ref} className={className}>
      {`${prefix}0${suffix}`}
    </span>
  );
}
