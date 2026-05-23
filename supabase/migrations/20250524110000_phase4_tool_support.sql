-- Phase 4: tables for tool wrappers (cache, availability, attempts, critic feedback)

-- ---------------------------------------------------------------------------
-- Travel matrix cache (Google Distance Matrix → avoid repeat API spend)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.travel_matrix_cache (
  cache_key text PRIMARY KEY,
  nodes jsonb NOT NULL,
  minutes jsonb NOT NULL,
  provider text NOT NULL DEFAULT 'google_maps',
  fetched_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS travel_matrix_cache_expires_idx
  ON public.travel_matrix_cache (expires_at);

COMMENT ON TABLE public.travel_matrix_cache IS
  'Cached NxN travel time matrices keyed by participating node coordinates.';

-- ---------------------------------------------------------------------------
-- Weather cache (Tomorrow.io or mock)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.weather_cache (
  cache_key text PRIMARY KEY,
  lat double precision NOT NULL,
  lng double precision NOT NULL,
  forecast_date date NOT NULL,
  data jsonb NOT NULL,
  provider text NOT NULL DEFAULT 'tomorrow_io',
  fetched_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS weather_cache_expires_idx ON public.weather_cache (expires_at);

-- ---------------------------------------------------------------------------
-- Per-crew daily availability overrides
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.crew_availability (
  crew_id text NOT NULL REFERENCES public.crews (id) ON DELETE CASCADE,
  available_date date NOT NULL,
  is_available boolean NOT NULL DEFAULT true,
  unavailable_reason text NOT NULL DEFAULT '',
  shift_start_minute integer NOT NULL DEFAULT 0 CHECK (shift_start_minute >= 0),
  shift_end_minute integer NOT NULL DEFAULT 480 CHECK (shift_end_minute > 0),
  PRIMARY KEY (crew_id, available_date)
);

-- ---------------------------------------------------------------------------
-- Optimizer run audit trail
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.schedule_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  target_date date NOT NULL,
  job_ids text[] NOT NULL DEFAULT '{}',
  crew_ids text[] NOT NULL DEFAULT '{}',
  optimizer_input jsonb,
  optimizer_result jsonb NOT NULL,
  status text NOT NULL CHECK (
    status = ANY (ARRAY['optimal', 'feasible', 'infeasible', 'timeout', 'error'])
  ),
  messages text[] NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS schedule_attempts_target_date_idx
  ON public.schedule_attempts (target_date DESC);

-- ---------------------------------------------------------------------------
-- Plan reviewer / critic feedback (per attempt or plan)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.critic_feedback (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  schedule_attempt_id uuid REFERENCES public.schedule_attempts (id) ON DELETE CASCADE,
  plan_id uuid REFERENCES public.plans (id) ON DELETE CASCADE,
  reviewer text NOT NULL DEFAULT 'plan_reviewer',
  score smallint CHECK (score IS NULL OR (score >= 0 AND score <= 100)),
  passed boolean NOT NULL DEFAULT false,
  concerns text[] NOT NULL DEFAULT '{}',
  narrative text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (schedule_attempt_id IS NOT NULL OR plan_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS critic_feedback_attempt_idx
  ON public.critic_feedback (schedule_attempt_id, created_at DESC);

CREATE INDEX IF NOT EXISTS critic_feedback_plan_idx
  ON public.critic_feedback (plan_id, created_at DESC);

ALTER TABLE public.travel_matrix_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.weather_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.crew_availability ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.schedule_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.critic_feedback ENABLE ROW LEVEL SECURITY;
