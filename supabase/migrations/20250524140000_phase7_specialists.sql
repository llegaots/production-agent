-- Phase 7: intake audit + job recurrence fields + client message drafts

-- Job scheduling preferences from natural-language intake
ALTER TABLE public.jobs
  ADD COLUMN IF NOT EXISTS recurrence_rule text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS preferred_day_of_week smallint
    CHECK (preferred_day_of_week IS NULL OR preferred_day_of_week BETWEEN 0 AND 6);

COMMENT ON COLUMN public.jobs.recurrence_rule IS
  'Human-readable recurrence, e.g. weekly:Tuesday. Empty for one-off jobs.';
COMMENT ON COLUMN public.jobs.preferred_day_of_week IS
  '0=Monday … 6=Sunday when client requests a recurring weekday.';

-- Raw intake audit trail
CREATE TABLE IF NOT EXISTS public.intake_requests (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  raw_text text NOT NULL,
  parsed_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  client_id text REFERENCES public.clients (id) ON DELETE SET NULL,
  job_id text REFERENCES public.jobs (id) ON DELETE SET NULL,
  parser_mode text NOT NULL DEFAULT 'rule'
    CHECK (parser_mode = ANY (ARRAY['rule', 'llm', 'hybrid'])),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS intake_requests_job_idx ON public.intake_requests (job_id);
CREATE INDEX IF NOT EXISTS intake_requests_created_idx ON public.intake_requests (created_at DESC);

-- Client comms drafts (table may already exist on remote — extend in place)
CREATE TABLE IF NOT EXISTS public.client_messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  plan_id uuid REFERENCES public.plans (id) ON DELETE SET NULL,
  job_id text NOT NULL REFERENCES public.jobs (id) ON DELETE CASCADE,
  message text NOT NULL,
  score smallint NOT NULL DEFAULT 0 CHECK (score BETWEEN 0 AND 100),
  guardrail_passed boolean NOT NULL DEFAULT false,
  guardrail_flags text[] NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.client_messages
  ADD COLUMN IF NOT EXISTS client_id text REFERENCES public.clients (id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'draft'
    CHECK (status = ANY (ARRAY['draft', 'queued', 'sent', 'failed'])),
  ADD COLUMN IF NOT EXISTS channel text NOT NULL DEFAULT 'email'
    CHECK (channel = ANY (ARRAY['email', 'sms', 'phone'])),
  ADD COLUMN IF NOT EXISTS subject text NOT NULL DEFAULT '';

COMMENT ON TABLE public.client_messages IS
  'Drafted client notifications (not sent until dispatcher approves in a later phase).';

ALTER TABLE public.intake_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.client_messages ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'intake_requests' AND policyname = 'authenticated_all'
  ) THEN
    CREATE POLICY authenticated_all ON public.intake_requests
      FOR ALL TO authenticated USING (true) WITH CHECK (true);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'client_messages' AND policyname = 'authenticated_all'
  ) THEN
    CREATE POLICY authenticated_all ON public.client_messages
      FOR ALL TO authenticated USING (true) WITH CHECK (true);
  END IF;
END $$;
