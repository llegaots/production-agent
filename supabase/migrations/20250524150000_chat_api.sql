-- Phase 8: chat API persistence

ALTER TABLE public.schedule_runs DROP CONSTRAINT IF EXISTS schedule_runs_status_check;
ALTER TABLE public.schedule_runs ADD CONSTRAINT schedule_runs_status_check CHECK (
  status = ANY (
    ARRAY['running', 'approved', 'rejected', 'needs_human_review', 'failed']
  )
);

CREATE TABLE IF NOT EXISTS public.chat_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  title text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.chat_messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL REFERENCES public.chat_sessions (id) ON DELETE CASCADE,
  sequence_number integer NOT NULL,
  role text NOT NULL CHECK (role = ANY (ARRAY['user', 'assistant', 'system', 'tool'])),
  content text NOT NULL DEFAULT '',
  tool_calls jsonb NOT NULL DEFAULT '[]'::jsonb,
  tool_results jsonb,
  schedule_preview jsonb,
  schedule_run_id uuid REFERENCES public.schedule_runs (id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (session_id, sequence_number)
);

CREATE INDEX IF NOT EXISTS chat_messages_session_idx
  ON public.chat_messages (session_id, sequence_number);

ALTER TABLE public.chat_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_messages ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'chat_sessions' AND policyname = 'authenticated_all'
  ) THEN
    CREATE POLICY authenticated_all ON public.chat_sessions
      FOR ALL TO authenticated USING (true) WITH CHECK (true);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'chat_messages' AND policyname = 'authenticated_all'
  ) THEN
    CREATE POLICY authenticated_all ON public.chat_messages
      FOR ALL TO authenticated USING (true) WITH CHECK (true);
  END IF;
END $$;
