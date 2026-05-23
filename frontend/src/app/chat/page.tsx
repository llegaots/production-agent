"use client";

import { SessionSidebar } from "@/components/chat/session-sidebar";

export default function ChatIndexPage() {
  return (
    <div className="flex h-screen">
      <SessionSidebar />
      <main className="flex flex-1 flex-col items-center justify-center p-8 text-center">
        <h1 className="text-lg font-semibold">Select or create a chat</h1>
        <p className="text-muted-foreground mt-2 max-w-md text-sm">
          Use the <strong>+</strong> button in the sidebar to start a new session. All messages and
          schedule previews load from Supabase — no local storage.
        </p>
      </main>
    </div>
  );
}
