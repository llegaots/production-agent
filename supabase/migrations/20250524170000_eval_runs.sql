-- Orchestrator eval harness: store raw trial metrics for regression tracking.

CREATE TABLE IF NOT EXISTS public.eval_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  eval_batch_id uuid NOT NULL,
  report_path text NOT NULL DEFAULT '',
  scenario_name text NOT NULL,
  trial_number integer NOT NULL CHECK (trial_number >= 1),
  schedule_run_id uuid REFERENCES public.schedule_runs (id) ON DELETE SET NULL,
  status text NOT NULL,
  approved boolean NOT NULL DEFAULT false,
  approved_within_cap boolean NOT NULL DEFAULT false,
  iteration_count integer NOT NULL DEFAULT 0,
  iteration_cap integer NOT NULL DEFAULT 4,
  total_drive_minutes integer NOT NULL DEFAULT 0,
  preference_violations integer NOT NULL DEFAULT 0,
  week_fill_score numeric,
  use_agent boolean NOT NULL DEFAULT false,
  langfuse_trace_id text,
  metrics jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (eval_batch_id, scenario_name, trial_number)
);

CREATE INDEX IF NOT EXISTS eval_runs_batch_idx ON public.eval_runs (eval_batch_id);
CREATE INDEX IF NOT EXISTS eval_runs_scenario_created_idx
  ON public.eval_runs (scenario_name, created_at DESC);

COMMENT ON TABLE public.eval_runs IS
  'Raw orchestrator eval trials (evals.run) for quality regression over time.';

ALTER TABLE public.eval_runs ENABLE ROW LEVEL SECURITY;

CREATE POLICY authenticated_select_eval_runs ON public.eval_runs
  FOR SELECT TO authenticated USING (true);

CREATE POLICY service_role_all_eval_runs ON public.eval_runs
  FOR ALL TO service_role USING (true) WITH CHECK (true);
