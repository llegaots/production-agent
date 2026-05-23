const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export type SseHandler = (event: string, data: Record<string, unknown>) => void;

/** Ephemeral SSE transport only — persisted messages come from Supabase Realtime. */
export async function streamChatMessage(
  sessionId: string,
  content: string,
  onEvent: SseHandler,
): Promise<void> {
  const res = await fetch(`${API_URL}/chat/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      content,
      use_orchestrator_agent: false,
    }),
  });

  if (!res.ok) {
    throw new Error(`Chat stream failed: ${res.status}`);
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
  const res = await fetch(`${API_URL}/schedules/${scheduleRunId}/approve`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`Approve failed: ${res.status}`);
  return res.json();
}

export async function rejectSchedule(scheduleRunId: string) {
  const res = await fetch(`${API_URL}/schedules/${scheduleRunId}/reject`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`Reject failed: ${res.status}`);
  return res.json();
}
