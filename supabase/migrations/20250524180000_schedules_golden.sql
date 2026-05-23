-- Dispatcher-approved schedules (1:1 with schedule_runs) and golden-set flag.

CREATE TABLE IF NOT EXISTS public.schedules (
  id uuid PRIMARY KEY REFERENCES public.schedule_runs (id) ON DELETE CASCADE,
  schedule_attempt_id uuid NOT NULL REFERENCES public.schedule_attempts (id) ON DELETE RESTRICT,
  week_start date NOT NULL,
  week_end date NOT NULL,
  target_date date NOT NULL,
  job_ids text[] NOT NULL DEFAULT '{}',
  crew_ids text[] NOT NULL DEFAULT '{}',
  user_request text NOT NULL DEFAULT '',
  assignments jsonb NOT NULL DEFAULT '{}'::jsonb,
  total_drive_minutes integer NOT NULL DEFAULT 0,
  preference_violations integer NOT NULL DEFAULT 0,
  golden boolean NOT NULL DEFAULT false,
  golden_marked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS schedules_golden_idx ON public.schedules (golden) WHERE golden = true;
CREATE INDEX IF NOT EXISTS schedules_week_idx ON public.schedules (week_start DESC);

COMMENT ON TABLE public.schedules IS
  'Human-approved schedule snapshot (from schedule_runs + final attempt). golden=true for regression evals.';
COMMENT ON COLUMN public.schedules.assignments IS
  'job_id → {"crew_id": "...", "day": "YYYY-MM-DD"} for assigned jobs; unassigned omit crew_id/day.';

ALTER TABLE public.schedules ENABLE ROW LEVEL SECURITY;

CREATE POLICY authenticated_all_schedules ON public.schedules
  FOR ALL TO authenticated USING (true) WITH CHECK (true);

CREATE POLICY service_role_all_schedules ON public.schedules
  FOR ALL TO service_role USING (true) WITH CHECK (true);

-- Golden eval drift history (optional regression tracking)
CREATE TABLE IF NOT EXISTS public.golden_eval_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  eval_batch_id uuid NOT NULL,
  report_path text NOT NULL DEFAULT '',
  schedule_id uuid NOT NULL REFERENCES public.schedules (id) ON DELETE CASCADE,
  replay_schedule_run_id uuid REFERENCES public.schedule_runs (id) ON DELETE SET NULL,
  same_crew_pct numeric NOT NULL DEFAULT 0,
  same_day_pct numeric NOT NULL DEFAULT 0,
  drive_minutes_delta integer NOT NULL DEFAULT 0,
  preference_violations_delta integer NOT NULL DEFAULT 0,
  metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS golden_eval_runs_batch_idx ON public.golden_eval_runs (eval_batch_id);
CREATE INDEX IF NOT EXISTS golden_eval_runs_schedule_idx ON public.golden_eval_runs (schedule_id, created_at DESC);

ALTER TABLE public.golden_eval_runs ENABLE ROW LEVEL SECURITY;

CREATE POLICY authenticated_select_golden_eval ON public.golden_eval_runs
  FOR SELECT TO authenticated USING (true);

CREATE POLICY service_role_all_golden_eval ON public.golden_eval_runs
  FOR ALL TO service_role USING (true) WITH CHECK (true);
