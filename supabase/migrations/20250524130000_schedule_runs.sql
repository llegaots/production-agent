-- Phase 6: orchestrator run log (Langfuse trace + iteration audit)

CREATE TABLE IF NOT EXISTS public.schedule_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_request text NOT NULL,
  week_start date NOT NULL,
  week_end date NOT NULL,
  status text NOT NULL DEFAULT 'running' CHECK (
    status = ANY (ARRAY['running', 'approved', 'needs_human_review', 'failed'])
  ),
  iteration_count integer NOT NULL DEFAULT 0,
  approved boolean NOT NULL DEFAULT false,
  best_schedule_attempt_id uuid REFERENCES public.schedule_attempts (id) ON DELETE SET NULL,
  final_schedule_attempt_id uuid REFERENCES public.schedule_attempts (id) ON DELETE SET NULL,
  langfuse_trace_id text,
  summary text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz
);

CREATE TABLE IF NOT EXISTS public.schedule_run_iterations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  schedule_run_id uuid NOT NULL REFERENCES public.schedule_runs (id) ON DELETE CASCADE,
  iteration_number integer NOT NULL CHECK (iteration_number >= 1),
  schedule_attempt_id uuid REFERENCES public.schedule_attempts (id) ON DELETE SET NULL,
  critic_feedback_id uuid REFERENCES public.critic_feedback (id) ON DELETE SET NULL,
  approved boolean NOT NULL DEFAULT false,
  feedback_prompt text NOT NULL DEFAULT '',
  issues text[] NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (schedule_run_id, iteration_number)
);

CREATE INDEX IF NOT EXISTS schedule_runs_week_idx ON public.schedule_runs (week_start DESC);
CREATE INDEX IF NOT EXISTS schedule_run_iterations_run_idx
  ON public.schedule_run_iterations (schedule_run_id, iteration_number);

ALTER TABLE public.schedule_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.schedule_run_iterations ENABLE ROW LEVEL SECURITY;

CREATE POLICY authenticated_all ON public.schedule_runs
  FOR ALL TO authenticated USING (true) WITH CHECK (true);
CREATE POLICY authenticated_all ON public.schedule_run_iterations
  FOR ALL TO authenticated USING (true) WITH CHECK (true);
