import type { DoorOutcome } from "@/lib/types";

/** Shared door-outcome styling for every map + legend, so colors never drift. */
export const outcomeColor: Record<DoorOutcome, string> = {
  lead: "#059e6e", // green — booked / strong interest
  answered: "#34d399", // light green — talked, neutral
  callback: "#f5a623", // amber — follow up later
  "not-interested": "#fb7185", // rose — declined
  "no-answer": "#cbd3cf", // grey — nobody home
};

export const outcomeLabel: Record<DoorOutcome, string> = {
  lead: "Lead",
  answered: "Answered",
  callback: "Callback",
  "not-interested": "Not interested",
  "no-answer": "No answer",
};

/** Display order for legends + tallies (best → worst → no-answer). */
export const OUTCOME_ORDER: DoorOutcome[] = [
  "lead",
  "answered",
  "callback",
  "not-interested",
  "no-answer",
];

export const escapeHtml = (s: string) =>
  s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
