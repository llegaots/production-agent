-- ============================================================================
-- RouteIQ — Leads (CRM). Run after 0001/0002.
-- ============================================================================

create table if not exists "D2D_Leads" (
  id                 uuid primary key default gen_random_uuid(),
  team_id            uuid references "D2D_Teams"(id) on delete set null,
  marketer_id        uuid references "D2D_Marketers"(id) on delete set null,
  route_id           uuid references "D2D_Routes"(id) on delete set null,
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

alter table "D2D_Leads" enable row level security;
drop policy if exists "read_all" on "D2D_Leads";
create policy "read_all" on "D2D_Leads" for select using (true);
