"use client";

import type { ChatMessage, SchedulePreview } from "@/lib/types";
import { SchedulePreviewTable } from "@/components/schedule/schedule-preview-table";
import { IterationProgress } from "@/components/schedule/iteration-progress";
import { cn } from "@/lib/utils";

type Props = {
  message: ChatMessage;
  /** Ephemeral streaming text (not persisted — UI only). */
  streamOverlay?: string;
};

export function MessageBubble({ message, streamOverlay }: Props) {
  const isUser = message.role === "user";
  const preview = message.schedule_preview as SchedulePreview | null;
  const showStream = streamOverlay && message.role === "assistant" && !message.content;

  return (
    <div className={cn("flex flex-col gap-2", isUser ? "items-end" : "items-start")}>
      <div
        className={cn(
          "max-w-[85%] rounded-lg px-3 py-2 text-sm",
          isUser ? "bg-primary text-primary-foreground" : "bg-muted",
          message.role === "tool" && "text-muted-foreground max-w-full text-xs italic",
        )}
      >
        {showStream ? streamOverlay : message.content || (message.role === "tool" ? "Tool step" : "")}
      </div>

      {message.schedule_run_id && !preview ? (
        <div className="w-full max-w-2xl">
          <IterationProgress scheduleRunId={message.schedule_run_id} />
        </div>
      ) : null}

      {preview ? (
        <div className="w-full max-w-2xl space-y-2">
          <IterationProgress scheduleRunId={preview.schedule_run_id} />
          <SchedulePreviewTable preview={preview} />
        </div>
      ) : null}
    </div>
  );
}
