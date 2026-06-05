"use client";

import { usePathname } from "next/navigation";
import { Search, Calendar, Bell, ChevronDown } from "lucide-react";
import { pageMeta } from "./nav";
import { LiveBadge } from "@/components/ui/pulse-dot";

function metaFor(pathname: string) {
  if (pageMeta[pathname]) return pageMeta[pathname];
  const base = "/" + (pathname.split("/")[1] ?? "");
  return pageMeta[base] ?? { title: "RouteIQ", subtitle: "" };
}

export function Topbar({ liveCount = 0 }: { liveCount?: number }) {
  const pathname = usePathname();
  const meta = metaFor(pathname);

  return (
    <header className="sticky top-0 z-30 border-b border-line bg-canvas/80 backdrop-blur-xl">
      <div className="flex items-center gap-4 px-5 py-4 lg:px-8">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2.5">
            <h1 className="truncate font-display text-2xl font-extrabold tracking-tight text-ink">
              {meta.title}
            </h1>
            {liveCount > 0 && <LiveBadge />}
          </div>
          {meta.subtitle && <p className="mt-0.5 truncate text-[13px] text-muted">{meta.subtitle}</p>}
        </div>

        <div className="hidden items-center md:flex">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-faint" />
            <input
              placeholder="Search leads, reps, routes…"
              className="h-10 w-56 rounded-xl border border-line bg-surface pl-9 pr-3 text-sm text-ink placeholder:text-faint shadow-soft outline-none transition-all focus:w-72 focus:border-primary-200 focus:ring-2 focus:ring-primary/15"
            />
          </div>
        </div>

        <button className="hidden h-10 items-center gap-2 rounded-xl border border-line bg-surface px-3 text-sm font-medium text-ink-soft shadow-soft transition-colors hover:bg-surface-muted sm:flex">
          <Calendar className="size-4 text-muted" />
          Today
          <ChevronDown className="size-3.5 text-faint" />
        </button>

        <button className="relative grid size-10 place-items-center rounded-xl border border-line bg-surface text-ink-soft shadow-soft transition-colors hover:bg-surface-muted">
          <Bell className="size-[18px]" />
          <span className="absolute right-2.5 top-2.5 size-2 rounded-full bg-rose ring-2 ring-surface" />
        </button>
      </div>
    </header>
  );
}
