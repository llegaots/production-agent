import { Badge, type BadgeProps } from "./badge";
import type { LeadStatus, RouteStatus, RepStatus } from "@/lib/types";

const leadMap: Record<LeadStatus, { variant: BadgeProps["variant"]; label: string }> = {
  new: { variant: "sky", label: "New" },
  qualified: { variant: "violet", label: "Qualified" },
  callback: { variant: "amber", label: "Callback" },
  appointment: { variant: "emerald", label: "Appointment" },
  won: { variant: "success", label: "Won" },
  lost: { variant: "neutral", label: "Lost" },
};

const routeMap: Record<RouteStatus, { variant: BadgeProps["variant"]; label: string }> = {
  active: { variant: "success", label: "Active" },
  scheduled: { variant: "sky", label: "Scheduled" },
  completed: { variant: "neutral", label: "Completed" },
};

const repMap: Record<RepStatus, { variant: BadgeProps["variant"]; label: string }> = {
  live: { variant: "success", label: "Live" },
  break: { variant: "warning", label: "On break" },
  offline: { variant: "neutral", label: "Offline" },
};

export function LeadStatusBadge({ status, size }: { status: LeadStatus; size?: BadgeProps["size"] }) {
  const m = leadMap[status];
  return (
    <Badge variant={m.variant} size={size} dot>
      {m.label}
    </Badge>
  );
}

export function RouteStatusBadge({ status, size }: { status: RouteStatus; size?: BadgeProps["size"] }) {
  const m = routeMap[status];
  return (
    <Badge variant={m.variant} size={size} dot={status === "active"}>
      {m.label}
    </Badge>
  );
}

export function RepStatusBadge({ status, size }: { status: RepStatus; size?: BadgeProps["size"] }) {
  const m = repMap[status];
  return (
    <Badge variant={m.variant} size={size} dot={status === "live"}>
      {m.label}
    </Badge>
  );
}
