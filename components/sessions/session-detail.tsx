"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import {
  ArrowLeft,
  DoorOpen,
  MessagesSquare,
  Sparkles,
  PhoneOff,
  Percent,
  Timer,
  Flag,
  Navigation,
} from "lucide-react";
import { Avatar } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Gauge } from "@/components/ui/gauge";
import { LiveBadge } from "@/components/ui/pulse-dot";
import { FieldMap } from "@/components/maps/field-map";
import { LiveTranscript } from "./live-transcript";
import { AgentPanel } from "./agent-panel";
import { DetectedLeads } from "./detected-leads";
import { MetricStat } from "./metric-stat";
import { fadeInUp, staggerContainer } from "@/lib/motion";
import { formatDuration } from "@/lib/utils";
import type { AgentInsight, Lead, Route, Session, TranscriptLine } from "@/lib/types";

/** Renders a single live session. Live data (transcript / insights / leads /
 *  position updates) will be streamed in via Supabase Realtime — for now those
 *  arrive as props and default to empty, showing each panel's standby state. */
export function SessionDetail({
  session,
  route,
  transcript = [],
  insights = [],
  detectedLeads = [],
  micLevel = 0,
  onEndSession,
}: {
  session: Session;
  route: Route | null;
  transcript?: TranscriptLine[];
  insights?: AgentInsight[];
  detectedLeads?: Lead[];
  micLevel?: number;
  onEndSession?: () => void;
}) {
  const firstName = session.repName.split(" ")[0];
  const durationMin = (Date.now() - new Date(session.startedAt).getTime()) / 60000;
  const answerRate = session.doors ? Math.round((session.conversations / session.doors) * 100) : 0;

  return (
    <div className="mx-auto flex max-w-[1500px] flex-col gap-5">
      <motion.div
        variants={fadeInUp}
        initial="hidden"
        animate="show"
        className="flex flex-col gap-4 rounded-3xl border border-line bg-surface p-5 shadow-card sm:flex-row sm:items-center sm:justify-between"
      >
        <div className="flex items-center gap-4">
          <Link
            href="/sessions"
            className="grid size-9 shrink-0 place-items-center rounded-xl border border-line text-muted transition-colors hover:bg-surface-muted hover:text-ink"
          >
            <ArrowLeft className="size-4.5" />
          </Link>
          <Avatar name={session.repName} tint="emerald" size="xl" status="live" />
          <div>
            <div className="flex items-center gap-2.5">
              <h2 className="font-display text-xl font-extrabold tracking-tight text-ink">
                {session.repName}
              </h2>
              <LiveBadge />
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-muted">
              <span className="inline-flex items-center gap-1">
                <Navigation className="size-3.5 text-primary-600" />
                {route?.name ?? session.territory}
              </span>
              <span className="text-faint">•</span>
              <span className="inline-flex items-center gap-1">
                <Timer className="size-3.5" />
                {formatDuration(durationMin)} on shift
              </span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-5">
          <Gauge value={session.grade} size={120} stroke={11} />
          <div className="hidden flex-col gap-2 sm:flex">
            <Button variant="secondary" size="sm">
              <Flag className="size-4" /> Flag moment
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={onEndSession}
              disabled={!onEndSession || session.status !== "live"}
            >
              End session
            </Button>
          </div>
        </div>
      </motion.div>

      <motion.div
        variants={staggerContainer(0.06)}
        initial="hidden"
        animate="show"
        className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5"
      >
        <MetricStat label="Doors" value={session.doors} icon={<DoorOpen className="size-4.5" />} />
        <MetricStat
          label="Conversations"
          value={session.conversations}
          icon={<MessagesSquare className="size-4.5" />}
          chip="bg-sky-50 text-[#0284c7]"
        />
        <MetricStat
          label="Leads"
          value={session.leads}
          icon={<Sparkles className="size-4.5" />}
          chip="bg-violet-50 text-[#6d28d9]"
        />
        <MetricStat
          label="No-answers"
          value={session.noAnswers}
          icon={<PhoneOff className="size-4.5" />}
          chip="bg-canvas-deep text-muted"
        />
        <MetricStat
          label="Answer rate"
          value={`${answerRate}%`}
          icon={<Percent className="size-4.5" />}
          chip="bg-amber-50 text-[#b45309]"
        />
      </motion.div>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-12">
        <div className="flex flex-col gap-5 xl:col-span-8">
          <div className="relative h-[440px] overflow-hidden rounded-3xl border border-line shadow-card">
            <div className="absolute left-4 top-4 z-10 flex items-center gap-2 rounded-full bg-surface/85 px-3 py-1.5 text-[12px] font-semibold text-ink shadow-soft backdrop-blur">
              <Navigation className="size-3.5 text-primary-600" />
              Live location · {answerRate}% answering
            </div>
            <FieldMap
              center={session.position}
              path={route?.path}
              trail={session.trail}
              live={session.position}
              liveLabel={firstName}
              progress={1}
              className="h-full"
            />
          </div>
          <div className="h-[460px]">
            <LiveTranscript
              transcript={transcript}
              activeSpeaker={null}
              micLevel={micLevel}
              repName={session.repName}
            />
          </div>
        </div>

        <div className="flex flex-col gap-5 xl:col-span-4">
          <div className="h-[540px]">
            <AgentPanel insights={insights} />
          </div>
          <DetectedLeads leads={detectedLeads} />
        </div>
      </div>
    </div>
  );
}
