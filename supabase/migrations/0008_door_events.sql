-- ============================================================================
-- RouteIQ — Door events: a pin per home the rep visited, with the GPS location,
-- the AI-classified outcome, and the notes/transcript excerpt behind it.
-- Powers the live coverage map. Run after 0006.
-- ============================================================================

create table if not exists "D2D_DoorEvents" (
  id                 uuid primary key default gen_random_uuid(),
  session_id         uuid not null references "D2D_Sessions"(id)  on delete cascade,
  marketer_id        uuid references "D2D_Marketers"(id)          on delete set null,
  at                 timestamptz not null default now(),
  lat                double precision,
  lng                double precision,
  outcome            text not null default 'no-answer'
                       check (outcome in ('answered','no-answer','callback','not-interested','lead')),
  address            text,
  note               text,             -- one-line manager-facing summary
  transcript_excerpt text,             -- the conversation at this door
  from_seq           int,
  to_seq             int,
  created_at         timestamptz not null default now()
);
create index if not exists d2d_door_session_idx on "D2D_DoorEvents" (session_id, at);

-- RLS — public read; writes go through the service-role client.
alter table "D2D_DoorEvents" enable row level security;
drop policy if exists "read_all" on "D2D_DoorEvents";
create policy "read_all" on "D2D_DoorEvents" for select using (true);

-- Realtime — door pins stream onto the manager's live map as they happen.
alter table "D2D_DoorEvents" replica identity full;
do $$
begin
  begin
    execute 'alter publication supabase_realtime add table "D2D_DoorEvents"';
  exception
    when duplicate_object then null;
    when undefined_object then null;
  end;
end $$;
