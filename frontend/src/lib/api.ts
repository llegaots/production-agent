const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export async function createChatSession(initialMessage: string) {
  const res = await fetch(`${API_URL}/chat/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ initial_message: initialMessage }),
  });
  if (!res.ok) {
    throw new Error(await res.text());
  }
  return res.json();
}

export async function postChatMessage(sessionId: string, content: string) {
  const res = await fetch(`${API_URL}/chat/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  if (!res.ok) {
    throw new Error(await res.text());
  }
  return res.body;
}

export async function approveSchedule(scheduleRunId: string) {
  const res = await fetch(`${API_URL}/schedules/${scheduleRunId}/approve`, {
    method: "POST",
  });
  if (!res.ok) {
    throw new Error(await res.text());
  }
  return res.json();
}

export async function rejectSchedule(scheduleRunId: string) {
  const res = await fetch(`${API_URL}/schedules/${scheduleRunId}/reject`, {
    method: "POST",
  });
  if (!res.ok) {
    throw new Error(await res.text());
  }
  return res.json();
}
