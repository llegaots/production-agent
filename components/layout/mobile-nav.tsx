"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { navItems } from "./nav";
import { Logo } from "./logo";

function isActive(pathname: string, href: string) {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(href + "/");
}

export function MobileNav() {
  const pathname = usePathname();

  return (
    <div className="border-b border-line bg-surface/70 backdrop-blur-xl lg:hidden">
      <div className="flex items-center justify-between px-5 pt-4">
        <Logo />
      </div>
      <div className="no-scrollbar flex gap-1.5 overflow-x-auto px-4 py-3">
        {navItems.map((item) => {
          const active = isActive(pathname, item.href);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "inline-flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-[13px] font-medium transition-colors",
                active
                  ? "bg-primary-50 text-primary-700 ring-1 ring-primary-100"
                  : "text-ink-soft hover:bg-surface-muted",
              )}
            >
              <Icon className="size-4" />
              {item.label}
            </Link>
          );
        })}
      </div>
    </div>
  );
}
