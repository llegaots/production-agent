"use client";

import { useEffect, useRef } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Sparkles, Mic } from "lucide-react";
import { cn } from "@/lib/utils";
import { streamItem } from "@/lib/motion";
import { EmptyState } from "@/components/ui/empty-state";
import { MicWave } from "./mic-wave";
import type { Speaker, TranscriptLine } from "@/lib/types";

function TypingDots() {
  return (
    <span className="inline-flex items-center gap-1">
      {[0, 1, 2].map((i) => (
        <motion.span
          key={i}
          className="size-1.5 rounded-full bg-current"
          animate={{ opacity: [0.3, 1, 0.3], y: [0, -2, 0] }}
          transition={{ duration: 0.9, repeat: Infinity, delay: i * 0.15 }}
        />
      ))}
    </span>
  );
}

export function LiveTranscript({
  transcript,
  activeSpeaker,
  micLevel,
  repName,
}: {
  transcript: TranscriptLine[];
  activeSpeaker: Speaker | null;
  micLevel: number;
  repName: string;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [transcript.length, activeSpeaker]);

  const speakingLabel =
    activeSpeaker === "rep"
      ? `${repName.split(" ")[0]} is speaking`
      : activeSpeaker === "prospect"
        ? "Prospect is speaking"
        : activeSpeaker === "agent"
          ? "Agent analyzing"
          : "Listening";

  return (
    <div className="flex h-full flex-col rounded-3xl border border-line bg-surface shadow-card">
      <div className="flex items-center justify-between border-b border-line px-5 py-4">
        <div>
          <h3 className="text-base font-bold tracking-tight text-ink">Live transcript</h3>
          <p className="text-[12px] text-muted">Auto-transcribed on-device</p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-[12px] font-medium text-muted">{speakingLabel}</span>
          <MicWave level={micLevel} className="h-7" />
        </div>
      </div>

      <div ref={scrollRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-5 py-4 pretty-scroll">
        {transcript.length === 0 && !activeSpeaker && (
          <EmptyState
            compact
            className="h-full"
            icon={<Mic className="size-5" />}
            title="Waiting for audio"
            description="The transcript streams in as the rep starts talking at the door."
          />
        )}
        <AnimatePresence initial={false}>
          {transcript.map((line) => {
            if (line.speaker === "agent") {
              return (
                <motion.div
                  key={line.id}
                  variants={streamItem}
                  initial="hidden"
                  animate="show"
                  exit="exit"
                  className="flex items-center justify-center gap-2 py-0.5"
                >
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-violet-50 px-2.5 py-1 text-[11px] font-medium text-[#6d28d9]">
                    <Sparkles className="size-3" />
                    {line.text}
                  </span>
                </motion.div>
              );
            }
            const isRep = line.speaker === "rep";
            return (
              <motion.div
                key={line.id}
                variants={streamItem}
                initial="hidden"
                animate="show"
                exit="exit"
                className={cn("flex flex-col gap-1", isRep ? "items-start" : "items-end")}
              >
                <span className="px-1 text-[11px] font-semibold uppercase tracking-wide text-faint">
                  {isRep ? repName.split(" ")[0] : "Prospect"}
                </span>
                <div
                  className={cn(
                    "max-w-[85%] rounded-2xl px-3.5 py-2.5 text-[13px] leading-relaxed shadow-soft",
                    isRep
                      ? "rounded-tl-md bg-primary-50 text-ink"
                      : "rounded-tr-md border border-line bg-surface text-ink-soft",
                  )}
                >
                  {line.text}
                </div>
              </motion.div>
            );
          })}
        </AnimatePresence>

        {activeSpeaker && activeSpeaker !== "agent" && (
          <div className={cn("flex", activeSpeaker === "rep" ? "justify-start" : "justify-end")}>
            <div
              className={cn(
                "rounded-2xl px-3.5 py-3 text-muted shadow-soft",
                activeSpeaker === "rep" ? "rounded-tl-md bg-primary-50/60" : "rounded-tr-md border border-line bg-surface",
              )}
            >
              <TypingDots />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
