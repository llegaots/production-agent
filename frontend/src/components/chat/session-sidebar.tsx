"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { subscribeTable } from "@/lib/realtime";
import type { ChatSession } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import { LogOut, MessageSquarePlus } from "lucide-react";

export function SessionSidebar() {
  const supabase = createClient();
  const router = useRouter();
  const pathname = usePathname();
  const [sessions, setSessions] = useState<ChatSession[]>([]);

  const reload = useCallback(async () => {
    const { data } = await supabase
      .from("chat_sessions")
      .select("*")
      .order("updated_at", { ascending: false })
      .limit(50);
    setSessions((data ?? []) as ChatSession[]);
  }, [supabase]);

  useEffect(() => {
    void reload();
    return subscribeTable(supabase, "chat-sessions-list", "chat_sessions", undefined, () =>
      void reload(),
    );
  }, [reload, supabase]);

  async function createSession() {
    const { data, error } = await supabase
      .from("chat_sessions")
      .insert({ title: "New dispatch chat" })
      .select()
      .single();
    if (error || !data) {
      alert(error?.message ?? "Could not create session");
      return;
    }
    router.push(`/chat/${data.id}`);
  }

  async function signOut() {
    await supabase.auth.signOut();
    router.push("/login");
    router.refresh();
  }

  return (
    <aside className="flex h-full w-64 flex-col border-r bg-muted/20">
      <div className="flex items-center justify-between border-b p-3">
        <span className="text-sm font-semibold">Sessions</span>
        <Button variant="ghost" size="icon" onClick={() => void createSession()} title="New chat">
          <MessageSquarePlus className="h-4 w-4" />
        </Button>
      </div>
      <ScrollArea className="flex-1">
        <ul className="p-2">
          {sessions.map((s) => {
            const href = `/chat/${s.id}`;
            const active = pathname === href;
            return (
              <li key={s.id}>
                <Link
                  href={href}
                  className={cn(
                    "block rounded-md px-2 py-2 text-sm transition-colors",
                    active ? "bg-primary/10 font-medium" : "hover:bg-muted",
                  )}
                >
                  <div className="truncate">{s.title || "Untitled"}</div>
                  <div className="text-muted-foreground truncate text-xs">
                    {new Date(s.updated_at).toLocaleString()}
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>
      </ScrollArea>
      <div className="border-t p-2">
        <Button variant="ghost" className="w-full justify-start" size="sm" onClick={() => void signOut()}>
          <LogOut className="mr-2 h-4 w-4" />
          Sign out
        </Button>
      </div>
    </aside>
  );
}
