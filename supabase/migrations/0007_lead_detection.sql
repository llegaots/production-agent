-- ============================================================================
-- RouteIQ — Auto lead detection (Phase 2). Self-contained: creates D2D_Leads if
-- 0003_leads.sql was never run, links leads to sessions, and wires Realtime.
-- Safe to run after 0001/0002/0006 regardless of whether 0003 ran.
-- ============================================================================

-- D2D_Leads — identical shape to 0003_leads.sql (idempotent if that already ran).
create table if not exists "D2D_Leads" (
  id                 uuid primary key default gen_random_uuid(),
  team_id            uuid references "D2D_Teams"(id)      on delete set null,
  marketer_id        uuid references "D2D_Marketers"(id)  on delete set null,
  route_id           uuid references "D2D_Routes"(id)     on delete set null,
  name               text not null,
  address            text,
  lat                double precision,
  lng                double precision,
  phone              text,
  email              text,
  status             text not null default 'new'
                       check (status in ('new','qualified','callback','appointment','won','lost')),
  score              int  not null default 50,
  territory          text,
  source             text not null default 'manual' check (source in ('auto-detected','manual')),
  summary            text,
  transcript_snippet text,
  tags               text[] not null default '{}',
  captured_at        timestamptz not null default now(),
  created_at         timestamptz not null default now()
);
create index if not exists d2d_leads_status_idx  on "D2D_Leads" (status);
create index if not exists d2d_leads_created_idx  on "D2D_Leads" (created_at desc);

-- Link auto-detected leads back to the session that produced them. Enables the
-- per-session "detected leads" panel and dedup within a session.
alter table "D2D_Leads"
  add column if not exists session_id uuid references "D2D_Sessions"(id) on delete set null;
create index if not exists d2d_leads_session_idx on "D2D_Leads" (session_id);

-- RLS — public read; writes go through the service-role client.
alter table "D2D_Leads" enable row level security;
drop policy if exists "read_all" on "D2D_Leads";
create policy "read_all" on "D2D_Leads" for select using (true);

-- Realtime — managers see auto-detected leads stream into the live session view.
alter table "D2D_Leads" replica identity full;
do $$
begin
  begin
    execute 'alter publication supabase_realtime add table "D2D_Leads"';
  exception
    when duplicate_object then null;   -- already a member
    when undefined_object then null;   -- publication missing (non-Supabase pg)
  end;
end $$;
