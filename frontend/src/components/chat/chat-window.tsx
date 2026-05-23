"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { subscribeTable } from "@/lib/realtime";
import { streamChatMessage } from "@/lib/api";
import type { ChatMessage, SchedulePreview } from "@/lib/types";
import { MessageBubble } from "@/components/chat/message-bubble";
import { IterationProgress } from "@/components/schedule/iteration-progress";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Loader2, Send } from "lucide-react";

type Props = {
  sessionId: string;
};

export function ChatWindow({ sessionId }: Props) {
  const supabase = createClient();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [statusLine, setStatusLine] = useState<string | null>(null);
  const [streamText, setStreamText] = useState("");
  const [livePreview, setLivePreview] = useState<SchedulePreview | null>(null);
  const [errorLine, setErrorLine] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const reloadMessages = useCallback(async () => {
    const { data, error } = await supabase
      .from("chat_messages")
      .select("*")
      .eq("session_id", sessionId)
      .order("sequence_number", { ascending: true });
    if (error) {
      console.error(error);
      setErrorLine(error.message);
      return;
    }
    setMessages((data ?? []) as ChatMessage[]);
    setLoading(false);
  }, [sessionId, supabase]);

  useEffect(() => {
    void reloadMessages();
    return subscribeTable(
      supabase,
      `chat-msgs:${sessionId}`,
      "chat_messages",
      `session_id=eq.${sessionId}`,
      () => void reloadMessages(),
    );
  }, [sessionId, reloadMessages, supabase]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamText, statusLine, livePreview]);

  async function handleSend() {
    const text = draft.trim();
    if (!text || sending) return;
    setDraft("");
    setSending(true);
    setStreamText("");
    setLivePreview(null);
    setErrorLine(null);
    setStatusLine("Sending…");

    try {
      await streamChatMessage(sessionId, text, (event, data) => {
        if (event === "status" && typeof data.message === "string") {
          setStatusLine(data.message);
        }
        if (event === "text_delta" && typeof data.text === "string") {
          setStreamText((prev) => prev + data.text);
          setStatusLine(null);
        }
        if (event === "schedule_preview") {
          setLivePreview(data as unknown as SchedulePreview);
          setStatusLine(null);
        }
        if (event === "error" && typeof data.message === "string") {
          setErrorLine(String(data.message));
        }
        if (event === "message_complete") {
          setStatusLine(null);
        }
      });
      await reloadMessages();
      setLivePreview(null);
    } catch (err) {
      console.error(err);
      setErrorLine(err instanceof Error ? err.message : "Send failed");
    } finally {
      setSending(false);
      setStreamText("");
      setStatusLine(null);
    }
  }

  const activeRunId = [...messages]
    .reverse()
    .find((m) => m.schedule_run_id)?.schedule_run_id;

  const showProgress =
    activeRunId && messages.every((m) => !m.schedule_preview) && !livePreview;

  return (
    <div className="flex h-full flex-col">
      {showProgress ? (
        <div className="border-b p-3">
          <div className="max-w-2xl">
            <IterationProgress scheduleRunId={activeRunId} />
          </div>
        </div>
      ) : null}

      <ScrollArea className="flex-1 p-4">
        {loading ? (
          <p className="text-muted-foreground text-sm">Loading messages from Supabase…</p>
        ) : messages.length === 0 && !streamText && !statusLine && !livePreview ? (
          <p className="text-muted-foreground text-sm">
            Ask to schedule next week&apos;s jobs. You&apos;ll see progress while the optimizer runs,
            then a crew schedule table appears here.
          </p>
        ) : (
          <div className="space-y-4">
            {messages.map((m) => (
              <MessageBubble key={m.id} message={m} />
            ))}
            {sending && (statusLine || streamText || livePreview || errorLine) ? (
              <div className="flex flex-col items-start gap-2">
                {statusLine ? (
                  <div className="text-muted-foreground flex items-center gap-2 text-sm">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    {statusLine}
                  </div>
                ) : null}
                {streamText ? (
                  <MessageBubble
                    message={{
                      id: "streaming",
                      session_id: sessionId,
                      sequence_number: 9999,
                      role: "assistant",
                      content: "",
                      tool_calls: [],
                      tool_results: null,
                      schedule_preview: null,
                      schedule_run_id: null,
                      created_at: new Date().toISOString(),
                    }}
                    streamOverlay={streamText}
                  />
                ) : null}
                {livePreview ? (
                  <MessageBubble
                    message={{
                      id: "streaming-preview",
                      session_id: sessionId,
                      sequence_number: 9998,
                      role: "assistant",
                      content: "Schedule preview",
                      tool_calls: [],
                      tool_results: null,
                      schedule_preview: livePreview,
                      schedule_run_id: livePreview.schedule_run_id,
                      created_at: new Date().toISOString(),
                    }}
                  />
                ) : null}
                {errorLine ? (
                  <Alert variant="destructive" className="max-w-2xl">
                    <AlertDescription>{errorLine}</AlertDescription>
                  </Alert>
                ) : null}
              </div>
            ) : null}
            <div ref={bottomRef} />
          </div>
        )}
      </ScrollArea>

      <div className="flex gap-2 border-t p-3">
        <Textarea
          placeholder="Message the production agent…"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={2}
          className="resize-none"
          disabled={sending}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void handleSend();
            }
          }}
        />
        <Button onClick={() => void handleSend()} disabled={sending || !draft.trim()} size="icon">
          {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
        </Button>
      </div>
    </div>
  );
}
