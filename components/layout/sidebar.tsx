"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion } from "framer-motion";
import { ChevronsUpDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { navItems } from "./nav";
import { Logo } from "./logo";
import { PulseDot } from "@/components/ui/pulse-dot";
import { Avatar } from "@/components/ui/avatar";

function isActive(pathname: string, href: string) {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(href + "/");
}

export function Sidebar({ liveCount = 0 }: { liveCount?: number }) {
  const pathname = usePathname();
  const groups = [
    { key: "workspace", label: "Workspace" },
    { key: "account", label: "Account" },
  ] as const;

  return (
    <aside className="sticky top-0 hidden h-screen w-[260px] shrink-0 flex-col gap-1 border-r border-line bg-surface/60 px-4 pb-4 pt-5 lg:flex">
      <div className="px-2">
        <Logo />
      </div>

      <nav className="mt-6 flex flex-1 flex-col gap-6">
        {groups.map((group) => (
          <div key={group.key} className="flex flex-col gap-1">
            <span className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-faint">
              {group.label}
            </span>
            {navItems
              .filter((i) => i.group === group.key)
              .map((item) => {
                const active = isActive(pathname, item.href);
                const Icon = item.icon;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={cn(
                      "group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-[14px] font-medium transition-colors duration-200",
                      active ? "text-primary-700" : "text-ink-soft hover:text-ink",
                    )}
                  >
                    {active && (
                      <motion.span
                        layoutId="sidebar-active"
                        className="absolute inset-0 rounded-xl bg-primary-50 ring-1 ring-primary-100"
                        transition={{ type: "spring", stiffness: 460, damping: 38 }}
                      />
                    )}
                    <Icon
                      className={cn(
                        "relative z-10 size-[18px] shrink-0 transition-transform duration-200 group-hover:scale-110",
                        active ? "text-primary-600" : "text-muted group-hover:text-ink-soft",
                      )}
                      strokeWidth={2}
                    />
                    <span className="relative z-10">{item.label}</span>
                    {item.badge === "live" && liveCount > 0 && (
                      <span className="relative z-10 ml-auto inline-flex items-center gap-1.5 rounded-full bg-primary-50 px-1.5 py-0.5 text-[10px] font-bold text-primary-700">
                        <PulseDot size="size-1.5" />
                        {liveCount}
                      </span>
                    )}
                  </Link>
                );
              })}
          </div>
        ))}
      </nav>

      <button className="mt-2 flex items-center gap-3 rounded-2xl border border-line bg-surface p-2.5 text-left shadow-soft transition-colors hover:bg-surface-muted">
        <Avatar name="Lucas Legatos" tint="emerald" size="md" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-semibold text-ink">Lucas Legatos</div>
          <div className="truncate text-[11px] text-muted">info@neptaai.com</div>
        </div>
        <ChevronsUpDown className="size-4 shrink-0 text-faint" />
      </button>
    </aside>
  );
}
