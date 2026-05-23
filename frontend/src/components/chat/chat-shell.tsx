"use client";

import { SessionSidebar } from "@/components/chat/session-sidebar";
import { ChatWindow } from "@/components/chat/chat-window";

type Props = {
  sessionId: string;
};

export function ChatShell({ sessionId }: Props) {
  return (
    <div className="flex h-screen">
      <SessionSidebar />
      <main className="flex flex-1 flex-col">
        <header className="border-b px-4 py-3">
          <h1 className="text-lg font-semibold">Production Agent</h1>
          <p className="text-muted-foreground text-xs">Dispatcher console — data from Supabase Realtime</p>
        </header>
        <ChatWindow sessionId={sessionId} />
      </main>
    </div>
  );
}
