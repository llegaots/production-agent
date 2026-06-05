import {
  LayoutDashboard,
  RadioTower,
  Contact,
  Route,
  Map,
  Users,
  CalendarDays,
  BookOpenText,
  Settings2,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
  group: "workspace" | "account";
  badge?: "live";
}

export const navItems: NavItem[] = [
  { label: "Dashboard", href: "/", icon: LayoutDashboard, group: "workspace" },
  { label: "Live Sessions", href: "/sessions", icon: RadioTower, group: "workspace", badge: "live" },
  { label: "Leads", href: "/leads", icon: Contact, group: "workspace" },
  { label: "Routes", href: "/routes", icon: Route, group: "workspace" },
  { label: "Coverage", href: "/coverage", icon: Map, group: "workspace" },
  { label: "Schedule", href: "/schedule", icon: CalendarDays, group: "workspace" },
  { label: "Team", href: "/team", icon: Users, group: "workspace" },
  { label: "Playbook", href: "/playbook", icon: BookOpenText, group: "workspace" },
  { label: "Settings", href: "/settings", icon: Settings2, group: "account" },
];

export const pageMeta: Record<string, { title: string; subtitle: string }> = {
  "/": { title: "Overview", subtitle: "Live field performance across all routes" },
  "/sessions": { title: "Live Sessions", subtitle: "Real-time monitoring of reps in the field" },
  "/leads": { title: "Leads", subtitle: "Every lead your team captured, auto-detected and graded" },
  "/routes": { title: "Routes", subtitle: "Plan territories and see what's covered vs. unhit" },
  "/coverage": { title: "Coverage", subtitle: "Every route across all shifts - see what your team has hit" },
  "/schedule": { title: "Schedule", subtitle: "Plan and assign field shifts across your team" },
  "/team": { title: "Team", subtitle: "Performance, pace and grades for every marketer" },
  "/playbook": { title: "Playbook", subtitle: "The script and objections your AI agents grade against" },
  "/settings": { title: "Settings", subtitle: "Workspace, integrations and notifications" },
};
