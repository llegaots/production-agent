-- ProductionAgent initial schema. Run once against a fresh Supabase project
-- (or another Postgres 14+ database). Applied via Supabase migration
-- "init_production_agent_schema".
--
-- Conventions
--   * Text PKs (`cli_001`, `job_001`, ...) are used for the human-curated
--     entities to keep parity with the in-memory demo seed. Plans and
--     their children use UUIDs because they are agent-produced.
--   * RLS is ENABLED on every table; no policies are granted to
--     anon/authenticated. The backend uses the service-role key, which
--     bypasses RLS. Add scoped policies later when end-user auth is
--     introduced.
--   * All check constraints are also enforced application-side (Pydantic),
--     but they live in the DB so direct SQL writes cannot corrupt state.

create extension if not exists pgcrypto;

-- ----- helpers -----
create or replace function public.set_updated_at()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- ----- clients -----
create table public.clients (
  id                text primary key,
  name              text not null,
  contact_email     text not null,
  contact_phone     text not null,
  preferred_contact text not null default 'email'
                      check (preferred_contact in ('email','phone','sms')),
  notes             text not null default '',
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);
comment on table public.clients is 'End-customers (residential, commercial, HOA) booking the service business.';

create trigger trg_clients_updated_at
before update on public.clients
for each row execute function public.set_updated_at();

alter table public.clients enable row level security;

-- ----- crews -----
create table public.crews (
  id            text primary key,
  name          text not null,
  members       text[] not null default '{}',
  skills        text[] not null default '{}',
  daily_minutes integer not null default 480 check (daily_minutes > 0),
  base_lat      double precision not null,
  base_lng      double precision not null,
  hourly_cost   numeric(10,2) not null default 0,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
comment on table public.crews is 'Field crews; one row per crew with its members, skills, and base location.';

create trigger trg_crews_updated_at
before update on public.crews
for each row execute function public.set_updated_at();

alter table public.crews enable row level security;

-- ----- equipment -----
create table public.equipment (
  id         text primary key,
  kind       text not null check (kind in (
    'pressure_washer','extension_pole','water_fed_pole',
    'scissor_lift','rope_kit','ladder_28','van'
  )),
  label      text not null,
  quantity   integer not null default 1 check (quantity >= 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
comment on table public.equipment is 'Inventory of capital equipment. Quantity supports same-day capacity checks.';

create trigger trg_equipment_updated_at
before update on public.equipment
for each row execute function public.set_updated_at();

alter table public.equipment enable row level security;

-- ----- crew_equipment (many-to-many loadout) -----
create table public.crew_equipment (
  crew_id      text not null references public.crews(id) on delete cascade,
  equipment_id text not null references public.equipment(id) on delete cascade,
  primary key (crew_id, equipment_id)
);
comment on table public.crew_equipment is 'Assigns equipment items to a crew. Used by the EquipmentAgent to enforce hard equipment constraints.';

create index ix_crew_equipment_equipment on public.crew_equipment(equipment_id);

alter table public.crew_equipment enable row level security;

-- ----- jobs -----
create table public.jobs (
  id                 text primary key,
  client_id          text not null references public.clients(id) on delete restrict,
  service_type       text not null check (service_type in (
    'window_cleaning','pressure_washing','gutter_cleaning',
    'solar_panel_cleaning','high_rise'
  )),
  address            text not null,
  lat                double precision not null,
  lng                double precision not null,
  estimated_minutes  integer not null check (estimated_minutes > 0),
  difficulty         smallint not null check (difficulty between 1 and 5),
  required_skills    text[] not null default '{}',
  required_equipment text[] not null default '{}',
  earliest_date      date not null,
  latest_date        date not null,
  price              numeric(10,2) not null default 0,
  status             text not null default 'pending' check (status in (
    'pending','scheduled','confirmed','rescheduled','cancelled','complete'
  )),
  notes              text not null default '',
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  check (earliest_date <= latest_date)
);
comment on table public.jobs is 'Service jobs to be planned. Status moves pending -> scheduled -> confirmed (or rescheduled/cancelled/complete).';

create index ix_jobs_status on public.jobs(status);
create index ix_jobs_client on public.jobs(client_id);
create index ix_jobs_window on public.jobs(earliest_date, latest_date);

create trigger trg_jobs_updated_at
before update on public.jobs
for each row execute function public.set_updated_at();

alter table public.jobs enable row level security;

-- ----- plans -----
create table public.plans (
  id                  uuid primary key default gen_random_uuid(),
  week_start          date not null,
  summary             text not null default '',
  conflicts           jsonb not null default '[]'::jsonb,
  unscheduled_job_ids text[] not null default '{}',
  created_at          timestamptz not null default now()
);
comment on table public.plans is 'A weekly plan produced by SupervisorAgent. Multiple plans can exist over time.';

create index ix_plans_week_start on public.plans(week_start desc);

alter table public.plans enable row level security;

-- ----- crew_days -----
create table public.crew_days (
  id                  uuid primary key default gen_random_uuid(),
  plan_id             uuid not null references public.plans(id) on delete cascade,
  crew_id             text not null references public.crews(id) on delete restrict,
  day                 date not null,
  total_drive_minutes integer not null default 0,
  total_work_minutes  integer not null default 0,
  utilization         numeric(4,3) not null default 0 check (utilization >= 0),
  overbooked          boolean not null default false,
  warnings            text[] not null default '{}',
  created_at          timestamptz not null default now(),
  unique (plan_id, crew_id, day)
);
comment on table public.crew_days is 'A crew''s scheduled day inside a plan, with totals and warnings.';

create index ix_crew_days_plan on public.crew_days(plan_id);

alter table public.crew_days enable row level security;

-- ----- scheduled_stops -----
create table public.scheduled_stops (
  id                    uuid primary key default gen_random_uuid(),
  crew_day_id           uuid not null references public.crew_days(id) on delete cascade,
  job_id                text not null references public.jobs(id) on delete restrict,
  stop_order            integer not null check (stop_order >= 0),
  start_minute          integer not null check (start_minute >= 0),
  travel_minutes_before integer not null default 0 check (travel_minutes_before >= 0),
  duration_minutes      integer not null check (duration_minutes > 0),
  unique (crew_day_id, stop_order)
);
comment on table public.scheduled_stops is 'One scheduled visit inside a crew_day. stop_order is the route position.';

create index ix_stops_job on public.scheduled_stops(job_id);
create index ix_stops_crew_day on public.scheduled_stops(crew_day_id);

alter table public.scheduled_stops enable row level security;

-- ----- client_messages -----
create table public.client_messages (
  id               uuid primary key default gen_random_uuid(),
  plan_id          uuid references public.plans(id) on delete cascade,
  job_id           text not null references public.jobs(id) on delete cascade,
  message          text not null,
  score            smallint not null default 0 check (score between 0 and 100),
  guardrail_passed boolean not null default true,
  guardrail_flags  text[] not null default '{}',
  created_at       timestamptz not null default now()
);
comment on table public.client_messages is 'Drafted confirmation/reschedule messages produced by ClientCommsAgent (with critic score and guardrail flags).';

create index ix_messages_plan_job on public.client_messages(plan_id, job_id);
create index ix_messages_job on public.client_messages(job_id);

alter table public.client_messages enable row level security;

-- ----- plan_reviews -----
create table public.plan_reviews (
  plan_id        uuid primary key references public.plans(id) on delete cascade,
  kpis           jsonb not null default '{}'::jsonb,
  risk_score     smallint not null default 0 check (risk_score between 0 and 100),
  top_concern    text,
  recommendation text,
  narrative      text not null default '',
  created_at     timestamptz not null default now()
);
comment on table public.plan_reviews is 'Structured review produced by PlanReviewerAgent. One row per plan.';

alter table public.plan_reviews enable row level security;

-- ----- agent_events -----
create table public.agent_events (
  id         uuid primary key default gen_random_uuid(),
  plan_id    uuid references public.plans(id) on delete cascade,
  job_id     text references public.jobs(id) on delete set null,
  agent      text not null,
  phase      text not null,
  message    text not null,
  detail     jsonb,
  created_at timestamptz not null default now()
);
comment on table public.agent_events is 'Append-only log of every event each agent emits. Useful for auditing and replay.';

create index ix_events_plan on public.agent_events(plan_id, created_at);
create index ix_events_agent on public.agent_events(agent, created_at desc);

alter table public.agent_events enable row level security;
