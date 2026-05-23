-- Phase 9: Supabase Realtime for dispatcher UI

DO $$
BEGIN
  BEGIN ALTER PUBLICATION supabase_realtime ADD TABLE public.chat_sessions;
  EXCEPTION WHEN duplicate_object THEN NULL; END;
  BEGIN ALTER PUBLICATION supabase_realtime ADD TABLE public.chat_messages;
  EXCEPTION WHEN duplicate_object THEN NULL; END;
  BEGIN ALTER PUBLICATION supabase_realtime ADD TABLE public.schedule_runs;
  EXCEPTION WHEN duplicate_object THEN NULL; END;
  BEGIN ALTER PUBLICATION supabase_realtime ADD TABLE public.schedule_run_iterations;
  EXCEPTION WHEN duplicate_object THEN NULL; END;
END $$;

-- Authenticated users (dispatcher) can read/write chat + schedules
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'chat_sessions' AND policyname = 'auth_read_chat_sessions'
  ) THEN
    CREATE POLICY auth_read_chat_sessions ON public.chat_sessions
      FOR SELECT TO authenticated USING (true);
    CREATE POLICY auth_insert_chat_sessions ON public.chat_sessions
      FOR INSERT TO authenticated WITH CHECK (true);
    CREATE POLICY auth_update_chat_sessions ON public.chat_sessions
      FOR UPDATE TO authenticated USING (true) WITH CHECK (true);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'chat_messages' AND policyname = 'auth_read_chat_messages'
  ) THEN
    CREATE POLICY auth_read_chat_messages ON public.chat_messages
      FOR SELECT TO authenticated USING (true);
    CREATE POLICY auth_insert_chat_messages ON public.chat_messages
      FOR INSERT TO authenticated WITH CHECK (true);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'schedule_runs' AND policyname = 'auth_read_schedule_runs'
  ) THEN
    CREATE POLICY auth_read_schedule_runs ON public.schedule_runs
      FOR SELECT TO authenticated USING (true);
    CREATE POLICY auth_update_schedule_runs ON public.schedule_runs
      FOR UPDATE TO authenticated USING (true) WITH CHECK (true);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'schedule_run_iterations' AND policyname = 'auth_read_schedule_run_iterations'
  ) THEN
    CREATE POLICY auth_read_schedule_run_iterations ON public.schedule_run_iterations
      FOR SELECT TO authenticated USING (true);
  END IF;
END $$;
