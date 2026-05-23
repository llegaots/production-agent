-- Phase 2: core operational schema (idempotent — safe on existing PRODUCTION AGENT DB).
-- "customers" in the product spec map to the `clients` table below.

CREATE EXTENSION IF NOT EXISTS postgis;

-- ---------------------------------------------------------------------------
-- Clients (customers)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.clients (
  id text PRIMARY KEY,
  name text NOT NULL,
  contact_email text NOT NULL,
  contact_phone text NOT NULL,
  preferred_contact text NOT NULL DEFAULT 'email'
    CHECK (preferred_contact = ANY (ARRAY['email', 'phone', 'sms'])),
  notes text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.clients IS
  'End-customers (residential, commercial, HOA). Product docs refer to these as customers.';

-- ---------------------------------------------------------------------------
-- Crews
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.crews (
  id text PRIMARY KEY,
  name text NOT NULL,
  members text[] NOT NULL DEFAULT '{}',
  skills text[] NOT NULL DEFAULT '{}',
  daily_minutes integer NOT NULL DEFAULT 480 CHECK (daily_minutes > 0),
  base_lat double precision NOT NULL,
  base_lng double precision NOT NULL,
  hourly_cost numeric NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.crews IS 'Field crews with skills array and depot coordinates.';

-- ---------------------------------------------------------------------------
-- Equipment inventory
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.equipment (
  id text PRIMARY KEY,
  kind text NOT NULL CHECK (
    kind = ANY (ARRAY[
      'pressure_washer', 'extension_pole', 'water_fed_pole',
      'scissor_lift', 'rope_kit', 'ladder_28', 'van'
    ])
  ),
  label text NOT NULL,
  quantity integer NOT NULL DEFAULT 1 CHECK (quantity >= 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Crew ↔ equipment assignments
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.crew_equipment (
  crew_id text NOT NULL REFERENCES public.crews (id) ON DELETE CASCADE,
  equipment_id text NOT NULL REFERENCES public.equipment (id) ON DELETE CASCADE,
  PRIMARY KEY (crew_id, equipment_id)
);

-- ---------------------------------------------------------------------------
-- Jobs
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.jobs (
  id text PRIMARY KEY,
  client_id text NOT NULL REFERENCES public.clients (id) ON DELETE RESTRICT,
  service_type text NOT NULL CHECK (
    service_type = ANY (ARRAY[
      'window_cleaning', 'pressure_washing', 'gutter_cleaning',
      'solar_panel_cleaning', 'high_rise'
    ])
  ),
  address text NOT NULL,
  lat double precision NOT NULL,
  lng double precision NOT NULL,
  location geography(Point, 4326)
    GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(lng, lat), 4326)::geography) STORED,
  estimated_minutes integer NOT NULL CHECK (estimated_minutes > 0),
  difficulty smallint NOT NULL CHECK (difficulty BETWEEN 1 AND 5),
  required_skills text[] NOT NULL DEFAULT '{}',
  required_equipment text[] NOT NULL DEFAULT '{}',
  earliest_date date NOT NULL,
  latest_date date NOT NULL,
  price numeric NOT NULL DEFAULT 0,
  status text NOT NULL DEFAULT 'pending' CHECK (
    status = ANY (ARRAY[
      'pending', 'scheduled', 'confirmed',
      'rescheduled', 'cancelled', 'complete'
    ])
  ),
  notes text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (latest_date >= earliest_date)
);

CREATE INDEX IF NOT EXISTS jobs_status_idx ON public.jobs (status);
CREATE INDEX IF NOT EXISTS jobs_client_id_idx ON public.jobs (client_id);
CREATE INDEX IF NOT EXISTS jobs_earliest_date_idx ON public.jobs (earliest_date);
CREATE INDEX IF NOT EXISTS jobs_location_idx ON public.jobs USING GIST (location);

-- ---------------------------------------------------------------------------
-- Scheduling artifacts (used in later phases; created now for FK integrity)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.plans (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  week_start date NOT NULL,
  summary text NOT NULL DEFAULT '',
  conflicts jsonb NOT NULL DEFAULT '[]'::jsonb,
  unscheduled_job_ids text[] NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.crew_days (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  plan_id uuid NOT NULL REFERENCES public.plans (id) ON DELETE CASCADE,
  crew_id text NOT NULL REFERENCES public.crews (id) ON DELETE RESTRICT,
  day date NOT NULL,
  total_drive_minutes integer NOT NULL DEFAULT 0,
  total_work_minutes integer NOT NULL DEFAULT 0,
  utilization numeric NOT NULL DEFAULT 0 CHECK (utilization >= 0),
  overbooked boolean NOT NULL DEFAULT false,
  warnings text[] NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (plan_id, crew_id, day)
);

CREATE TABLE IF NOT EXISTS public.scheduled_stops (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  crew_day_id uuid NOT NULL REFERENCES public.crew_days (id) ON DELETE CASCADE,
  job_id text NOT NULL REFERENCES public.jobs (id) ON DELETE RESTRICT,
  stop_order integer NOT NULL CHECK (stop_order >= 0),
  start_minute integer NOT NULL CHECK (start_minute >= 0),
  travel_minutes_before integer NOT NULL DEFAULT 0 CHECK (travel_minutes_before >= 0),
  duration_minutes integer NOT NULL CHECK (duration_minutes > 0),
  UNIQUE (crew_day_id, stop_order)
);

-- Enable RLS on all app tables (policies added in a later migration)
ALTER TABLE public.clients ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.crews ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.equipment ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.crew_equipment ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.crew_days ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.scheduled_stops ENABLE ROW LEVEL SECURITY;
