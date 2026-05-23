"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { subscribeTable } from "@/lib/realtime";
import { streamChatMessage } from "@/lib/api";
import type { ChatMessage } from "@/lib/types";
import { MessageBubble } from "@/components/chat/message-bubble";
import { IterationProgress } from "@/components/schedule/iteration-progress";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Send } from "lucide-react";

type Props = {
  sessionId: string;
};

export function ChatWindow({ sessionId }: Props) {
  const supabase = createClient();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  /** UI-only buffer while SSE streams; cleared when Supabase delivers the row. */
  const [streamText, setStreamText] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  const reloadMessages = useCallback(async () => {
    const { data, error } = await supabase
      .from("chat_messages")
      .select("*")
      .eq("session_id", sessionId)
      .order("sequence_number", { ascending: true });
    if (error) {
      console.error(error);
      return;
    }
    setMessages((data ?? []) as ChatMessage[]);
    setLoading(false);
    setStreamText("");
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
  }, [messages, streamText]);

  async function handleSend() {
    const text = draft.trim();
    if (!text || sending) return;
    setDraft("");
    setSending(true);
    setStreamText("");

    try {
      await streamChatMessage(sessionId, text, (event, data) => {
        if (event === "text_delta" && typeof data.text === "string") {
          setStreamText((prev) => prev + data.text);
        }
        if (event === "message_complete") {
          void reloadMessages();
        }
      });
      await reloadMessages();
    } catch (err) {
      console.error(err);
      alert(err instanceof Error ? err.message : "Send failed");
    } finally {
      setSending(false);
      setStreamText("");
    }
  }

  const activeRunId = [...messages]
    .reverse()
    .find((m) => m.schedule_run_id)?.schedule_run_id;

  return (
    <div className="flex h-full flex-col">
      {activeRunId && messages.every((m) => !m.schedule_preview) ? (
        <div className="border-b p-3">
          <div className="max-w-2xl">
            <IterationProgress scheduleRunId={activeRunId} />
          </div>
        </div>
      ) : null}

      <ScrollArea className="flex-1 p-4">
        {loading ? (
          <p className="text-muted-foreground text-sm">Loading messages from Supabase…</p>
        ) : messages.length === 0 && !streamText ? (
          <p className="text-muted-foreground text-sm">
            Ask to schedule next week&apos;s jobs. The orchestrator runs as a tool and previews
            appear here via Realtime.
          </p>
        ) : (
          <div className="space-y-4">
            {messages.map((m) => (
              <MessageBubble key={m.id} message={m} />
            ))}
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
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void handleSend();
            }
          }}
        />
        <Button onClick={() => void handleSend()} disabled={sending || !draft.trim()} size="icon">
          <Send className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
