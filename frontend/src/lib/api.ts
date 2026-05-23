import { getApiBase } from "@/lib/api-base";

export type SseHandler = (event: string, data: Record<string, unknown>) => void;

/** Ephemeral SSE transport only — persisted messages come from Supabase Realtime. */
export async function streamChatMessage(
  sessionId: string,
  content: string,
  onEvent: SseHandler,
): Promise<void> {
  const res = await fetch(`${getApiBase()}/chat/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      content,
    }),
  });

  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(
      detail ? `Chat stream failed (${res.status}): ${detail.slice(0, 200)}` : `Chat stream failed: ${res.status}`,
    );
  }

  const reader = res.body?.getReader();
  if (!reader) throw new Error("No response body");

  const decoder = new TextDecoder();
  let buffer = "";
  let eventName = "message";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (line.startsWith("event:")) {
        eventName = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        const raw = line.slice(5).trim();
        try {
          onEvent(eventName, JSON.parse(raw) as Record<string, unknown>);
        } catch {
          /* skip malformed */
        }
        eventName = "message";
      }
    }
  }
}

export async function approveSchedule(scheduleRunId: string) {
  const res = await fetch(`${getApiBase()}/schedules/${scheduleRunId}/approve`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`Approve failed: ${res.status}`);
  return res.json();
}

export async function rejectSchedule(scheduleRunId: string) {
  const res = await fetch(`${getApiBase()}/schedules/${scheduleRunId}/reject`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`Reject failed: ${res.status}`);
  return res.json();
}
