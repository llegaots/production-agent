"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Play, Loader2, Square, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/* Start / stop the live field demo. When reps are already live (`running`) it
   becomes a Stop control; the background playback keeps the reps walking the
   route for ~10 min on its own, or until stopped here. */
export function DemoButton({
  className,
  size = "sm",
  running = false,
}: {
  className?: string;
  size?: "sm" | "md";
  running?: boolean;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState(false);

  const hit = async (path: string) => {
    setBusy(true);
    setError(false);
    setMsg("");
    try {
      const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      const json = await res.json();
      if (!res.ok) {
        setError(true);
        setMsg(json.error ?? "Something went wrong.");
        return false;
      }
      router.refresh();
      return json;
    } catch (e) {
      setError(true);
      setMsg(e instanceof Error ? e.message : "Network error");
      return false;
    } finally {
      setBusy(false);
    }
  };

  const start = async () => {
    const json = await hit("/api/demo/start");
    if (json) setMsg(`${json.started} rep${json.started === 1 ? "" : "s"} live - click a rep to watch`);
  };
  const stop = async () => {
    const json = await hit("/api/demo/stop");
    if (json) setMsg("Demo stopped.");
  };

  return (
    <div className={cn("flex flex-col items-end gap-1.5", className)}>
      <Button
        size={size}
        variant={running ? "secondary" : "primary"}
        onClick={running ? stop : start}
        disabled={busy}
      >
        {busy ? <Loader2 className="size-4 animate-spin" /> : running ? <Square className="size-4" /> : <Play className="size-4" />}
        {busy ? (running ? "Stopping…" : "Starting…") : running ? "Stop demo" : "Start live demo"}
      </Button>
      {msg && (
        <span className={cn("inline-flex items-center gap-1 text-[11px] font-medium", error ? "text-[#be123c]" : "text-primary-700")}>
          {error && <AlertTriangle className="size-3" />}
          {msg}
        </span>
      )}
    </div>
  );
}
