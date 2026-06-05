-- ============================================================================
-- RouteIQ — D2D core schema (teams, marketers, shifts, routes, generations)
-- Run in the Supabase SQL editor (or `supabase db push`).
-- ============================================================================

create extension if not exists postgis;
create extension if not exists pgcrypto;

-- ── Teams ────────────────────────────────────────────────────────────────────
create table if not exists "D2D_Teams" (
  id          uuid primary key default gen_random_uuid(),
  name        text not null,
  created_at  timestamptz not null default now()
);

-- ── Marketers (maps to the app's `Rep`) ──────────────────────────────────────
create table if not exists "D2D_Marketers" (
  id              uuid primary key default gen_random_uuid(),
  team_id         uuid references "D2D_Teams"(id) on delete set null,
  name            text not null,
  email           text,
  phone           text,
  avatar_tint     text not null default 'emerald',
  status          text not null default 'offline' check (status in ('live','break','offline')),
  home_territory  text,
  joined_at       date not null default current_date,
  created_at      timestamptz not null default now()
);

-- ── Route generation jobs (the agent runs) ───────────────────────────────────
create table if not exists "D2D_RouteGenerations" (
  id            uuid primary key default gen_random_uuid(),
  team_id       uuid references "D2D_Teams"(id) on delete set null,
  area_input    text not null,
  params        jsonb not null default '{}'::jsonb,
  status        text not null default 'queued' check (status in ('queued','running','done','error')),
  stage         text not null default 'queued',
  progress      int  not null default 0,
  agent_summary text,
  error         text,
  created_at    timestamptz not null default now(),
  completed_at  timestamptz
);

-- ── Routes ───────────────────────────────────────────────────────────────────
create table if not exists "D2D_Routes" (
  id            uuid primary key default gen_random_uuid(),
  team_id       uuid references "D2D_Teams"(id) on delete set null,
  generation_id uuid references "D2D_RouteGenerations"(id) on delete set null,
  name          text not null,
  territory     text not null,
  area_input    text,
  status        text not null default 'scheduled' check (status in ('active','scheduled','completed')),
  center        geography(Point, 4326),
  path          jsonb not null default '[]'::jsonb,        -- [{lat,lng}, ...] for the UI
  coverage_geom geography(Geometry, 4326),                 -- covered streets (linestring)
  bounds        jsonb,
  doors_planned int  not null default 0,
  doors_hit     int  not null default 0,
  answered      int  not null default 0,
  leads         int  not null default 0,
  coverage_pct  int  not null default 0,
  scheduled_for date,
  created_at    timestamptz not null default now()
);
create index if not exists d2d_routes_coverage_gix on "D2D_Routes" using gist (coverage_geom);
create index if not exists d2d_routes_center_gix   on "D2D_Routes" using gist (center);
create index if not exists d2d_routes_created_idx   on "D2D_Routes" (created_at desc);

-- ── Shifts (maps to the app's `Shift`) ───────────────────────────────────────
create table if not exists "D2D_Shifts" (
  id           uuid primary key default gen_random_uuid(),
  marketer_id  uuid references "D2D_Marketers"(id) on delete cascade,
  route_id     uuid references "D2D_Routes"(id) on delete set null,
  date         date not null,
  start_time   text not null,                              -- 'HH:mm'
  end_time     text not null,
  status       text not null default 'scheduled' check (status in ('scheduled','active','completed')),
  notes        text,
  created_at   timestamptz not null default now()
);
create index if not exists d2d_shifts_date_idx on "D2D_Shifts" (date);

-- ── Route assignments (the pair — 2 marketers per route) ─────────────────────
create table if not exists "D2D_RouteAssignments" (
  id           uuid primary key default gen_random_uuid(),
  route_id     uuid not null references "D2D_Routes"(id) on delete cascade,
  marketer_id  uuid not null references "D2D_Marketers"(id) on delete cascade,
  created_at   timestamptz not null default now(),
  unique (route_id, marketer_id)
);

-- ============================================================================
-- RPCs
-- ============================================================================

-- Recent covered streets intersecting a bbox → GeoJSON, so the planner can
-- avoid assigning the same streets twice.
create or replace function d2d_recent_coverage(
  min_lng float8, min_lat float8, max_lng float8, max_lat float8, since_days int default 60
) returns table (id uuid, name text, created_at timestamptz, coverage_geojson text)
language sql stable as $$
  select r.id, r.name, r.created_at, ST_AsGeoJSON(r.coverage_geom::geometry)
  from "D2D_Routes" r
  where r.coverage_geom is not null
    and r.created_at >= now() - make_interval(days => since_days)
    and ST_Intersects(
      r.coverage_geom,
      ST_MakeEnvelope(min_lng, min_lat, max_lng, max_lat, 4326)::geography
    );
$$;

-- Insert a route, building PostGIS geometry from the path array of {lat,lng}.
create or replace function d2d_insert_route(
  p_team_id uuid, p_generation_id uuid, p_name text, p_territory text,
  p_area_input text, p_status text, p_path jsonb, p_bounds jsonb,
  p_doors_planned int, p_scheduled_for date
) returns uuid
language plpgsql as $$
declare
  v_id uuid;
  v_line geometry;
begin
  select ST_MakeLine(
           array_agg(
             ST_SetSRID(ST_MakePoint((pt->>'lng')::float8, (pt->>'lat')::float8), 4326)
             order by ord
           )
         )
    into v_line
    from jsonb_array_elements(p_path) with ordinality as t(pt, ord);

  insert into "D2D_Routes"(
    team_id, generation_id, name, territory, area_input, status, path, bounds,
    center, coverage_geom, doors_planned, scheduled_for
  ) values (
    p_team_id, p_generation_id, p_name, p_territory, p_area_input, p_status, p_path, p_bounds,
    case when v_line is null then null else ST_Centroid(v_line)::geography end,
    case when v_line is null then null else v_line::geography end,
    p_doors_planned, p_scheduled_for
  )
  returning id into v_id;
  return v_id;
end $$;

-- ============================================================================
-- Row Level Security — public read; writes go through the service-role client.
-- ============================================================================
do $$
declare t text;
begin
  foreach t in array array[
    'D2D_Teams','D2D_Marketers','D2D_Shifts','D2D_Routes','D2D_RouteAssignments','D2D_RouteGenerations'
  ] loop
    execute format('alter table %I enable row level security;', t);
    execute format('drop policy if exists "read_all" on %I;', t);
    execute format('create policy "read_all" on %I for select using (true);', t);
  end loop;
end $$;
