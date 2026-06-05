-- ============================================================================
-- RouteIQ — Live sessions: recording, live transcript, agent insights.
-- Run after 0001/0002/0003 and 0004_playbook (which owns the D2D_Playbooks table).
-- ============================================================================

-- ── Sessions (maps to the app's `Session`) ───────────────────────────────────
create table if not exists "D2D_Sessions" (
  id            uuid primary key default gen_random_uuid(),
  team_id       uuid references "D2D_Teams"(id)    on delete set null,
  marketer_id   uuid references "D2D_Marketers"(id) on delete set null,
  route_id      uuid references "D2D_Routes"(id)    on delete set null,
  shift_id      uuid references "D2D_Shifts"(id)    on delete set null,
  status        text not null default 'live' check (status in ('live','paused','completed')),
  started_at    timestamptz not null default now(),
  ended_at      timestamptz,
  territory     text,
  doors         int  not null default 0,
  conversations int  not null default 0,
  leads         int  not null default 0,
  no_answers    int  not null default 0,
  grade         int  not null default 0,
  lat           double precision,
  lng           double precision,
  audio_path    text,                       -- storage prefix: session-audio/{id}/
  duration_sec  int  not null default 0,
  created_at    timestamptz not null default now()
);
create index if not exists d2d_sessions_status_idx  on "D2D_Sessions" (status);
create index if not exists d2d_sessions_started_idx  on "D2D_Sessions" (started_at desc);

-- ── Transcript lines (maps to the app's `TranscriptLine`) ─────────────────────
-- One row per finalized utterance. Streamed to managers via Supabase Realtime.
create table if not exists "D2D_TranscriptLines" (
  id          uuid primary key default gen_random_uuid(),
  session_id  uuid not null references "D2D_Sessions"(id) on delete cascade,
  seq         int  not null default 0,          -- monotonic order within a session
  at          timestamptz not null default now(),
  speaker     text not null default 'prospect' check (speaker in ('rep','prospect','agent')),
  text        text not null,
  sentiment   real,                              -- -1..1, optional
  is_final    boolean not null default true,
  created_at  timestamptz not null default now()
);
create index if not exists d2d_transcript_session_seq_idx on "D2D_TranscriptLines" (session_id, seq);

-- ── Agent insights (maps to the app's `AgentInsight`) — written by Phase 2/3 ──
create table if not exists "D2D_AgentInsights" (
  id           uuid primary key default gen_random_uuid(),
  session_id   uuid not null references "D2D_Sessions"(id) on delete cascade,
  at           timestamptz not null default now(),
  kind         text not null default 'coaching'
                 check (kind in ('objection','script-adherence','pace','lead-detected','coaching','tone')),
  title        text not null,
  detail       text not null default '',
  score        int,
  objection_id text,
  created_at   timestamptz not null default now()
);
create index if not exists d2d_insights_session_idx on "D2D_AgentInsights" (session_id, at);

-- ============================================================================
-- Audio storage — private bucket; writes/reads go through the service-role
-- client (which bypasses Storage RLS), so no object policies are needed.
-- ============================================================================
insert into storage.buckets (id, name, public)
values ('session-audio', 'session-audio', false)
on conflict (id) do nothing;

-- ============================================================================
-- Row Level Security — public read; writes go through the service-role client.
-- (D2D_Playbooks RLS is owned by 0004_playbook.sql.)
-- ============================================================================
do $$
declare t text;
begin
  foreach t in array array['D2D_Sessions','D2D_TranscriptLines','D2D_AgentInsights'] loop
    execute format('alter table %I enable row level security;', t);
    execute format('drop policy if exists "read_all" on %I;', t);
    execute format('create policy "read_all" on %I for select using (true);', t);
  end loop;
end $$;

-- ============================================================================
-- Realtime — managers subscribe to transcript/insight/lead inserts + session
-- updates. Idempotent: skip tables already in the publication.
-- ============================================================================
-- REPLICA IDENTITY FULL lets Realtime filter on non-PK columns (e.g. session_id)
-- and include full rows on update. (The client also filters defensively.)
alter table "D2D_Sessions" replica identity full;
alter table "D2D_TranscriptLines" replica identity full;
alter table "D2D_AgentInsights" replica identity full;

do $$
declare t text;
begin
  foreach t in array array[
    'D2D_TranscriptLines','D2D_AgentInsights','D2D_Sessions','D2D_Leads'
  ] loop
    -- Skip tables that don't exist yet (e.g. D2D_Leads before 0003_leads.sql).
    if to_regclass(format('public.%I', t)) is null then
      continue;
    end if;
    begin
      execute format('alter publication supabase_realtime add table %I;', t);
    exception
      when duplicate_object then null;   -- already a member
      when undefined_object then null;   -- publication missing (non-Supabase pg)
    end;
  end loop;
end $$;

-- ============================================================================
-- Seed a starter playbook (Apex Exteriors — roofing D2D) so live grading and the
-- playbook page have content. The table + its unique(team_id) come from
-- 0004_playbook.sql; this is conflict-safe and won't clobber a user-authored one.
-- ============================================================================
do $seed$
begin
  if to_regclass('public."D2D_Playbooks"') is null then
    raise notice 'D2D_Playbooks not found — run 0004_playbook.sql to seed a playbook.';
    return;
  end if;
  insert into "D2D_Playbooks" (team_id, script_title, script, objections, grading_criteria)
  values (
  'd2d70000-0000-0000-0000-000000000001',
  'Apex Exteriors — Doorstep Roofing Script',
  $script$OPENER
"Hi, I'm {name} with Apex Exteriors — we're the crew doing the roof and siding
inspections here on {street} this week. I'm not selling anything today; we're just
letting neighbours know we found some storm wear on a few roofs nearby and offering
a free 10-minute inspection. Have you had your roof looked at since the last big storm?"

DISCOVER
- How long have you owned the home?
- Noticed any leaks, missing shingles, or higher energy bills?
- Has your insurance company been out recently?

VALUE
"Most of our neighbours don't realize storm damage is often covered by insurance — we
handle the whole claim. The inspection is free and there's no obligation. Worst case,
you get peace of mind in writing."

CLOSE / SET THE APPOINTMENT
"I've got an inspector on {street} tomorrow between {window}. I can lock in a free
10-minute look — does morning or afternoon work better for you?"$script$,
  $objections$[
    {"id":"obj-price","trigger":"How much does this cost?","category":"price","handle":"The inspection is completely free and there's no obligation. If we do find storm damage, most repairs are covered by your insurance — we work directly with your provider so it's typically just your deductible.","frequency":42,"successRate":61},
    {"id":"obj-timing","trigger":"Now's not a good time / I'm busy","category":"timing","handle":"Totally understand — I won't take your time now. The inspection itself is only 10 minutes and I've got someone on the street tomorrow. Would morning or afternoon be easier?","frequency":55,"successRate":48},
    {"id":"obj-trust","trigger":"I've never heard of you / sounds like a scam","category":"trust","handle":"Fair — I'd be skeptical too. We're local, fully licensed and insured, and I can show you the homes we're working on right here on the street. Here's my card and our Google reviews.","frequency":33,"successRate":54},
    {"id":"obj-need","trigger":"My roof is fine / it's new","category":"need","handle":"That's great to hear. Even newer roofs can take hidden wind and hail damage that voids warranties if it's not documented. The free inspection just gives you a dated record — useful if you ever file a claim.","frequency":38,"successRate":45},
    {"id":"obj-authority","trigger":"I need to talk to my spouse","category":"authority","handle":"Absolutely, this should be a joint decision. The inspection is free and commits you to nothing — why don't we book a time when you're both home so you both hear the findings together?","frequency":29,"successRate":52},
    {"id":"obj-stall","trigger":"Leave me some information / I'll call you","category":"stall","handle":"Happy to — here's my card. Since I'm already on the street, would it be easier to just grab a quick 10-minute slot tomorrow so you don't have to chase me down? No obligation at all.","frequency":47,"successRate":36}
  ]$objections$::jsonb,
  $criteria$[
    {"id":"opener","label":"Opener & rapport","weight":20,"description":"Introduces self/company, states the free-inspection reason, opens with a question rather than a pitch."},
    {"id":"discovery","label":"Discovery questions","weight":20,"description":"Asks about ownership, prior damage/leaks, and insurance history before pitching."},
    {"id":"objections","label":"Objection handling","weight":25,"description":"Recognizes the objection, stays calm, and uses the approved handle for that category."},
    {"id":"value","label":"Value framing","weight":15,"description":"Frames the inspection as free, no-obligation, insurance-covered, and low-risk."},
    {"id":"close","label":"Closing / appointment set","weight":20,"description":"Asks for the appointment with an assumptive either/or close and locks a specific window."}
  ]$criteria$::jsonb
  )
  on conflict (team_id) do nothing;
end $seed$;
