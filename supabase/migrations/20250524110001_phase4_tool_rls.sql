-- RLS for Phase 4 tool tables (match Phase 2 dispatcher pattern)

DO $$
DECLARE
  t text;
  tables text[] := ARRAY[
    'travel_matrix_cache', 'weather_cache', 'crew_availability',
    'schedule_attempts', 'critic_feedback'
  ];
  pol text;
BEGIN
  FOREACH t IN ARRAY tables LOOP
    FOR pol IN
      SELECT policyname FROM pg_policies
      WHERE schemaname = 'public' AND tablename = t
    LOOP
      EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', pol, t);
    END LOOP;
  END LOOP;
END $$;

CREATE POLICY authenticated_all ON public.travel_matrix_cache
  FOR ALL TO authenticated USING (true) WITH CHECK (true);
CREATE POLICY authenticated_all ON public.weather_cache
  FOR ALL TO authenticated USING (true) WITH CHECK (true);
CREATE POLICY authenticated_all ON public.crew_availability
  FOR ALL TO authenticated USING (true) WITH CHECK (true);
CREATE POLICY authenticated_all ON public.schedule_attempts
  FOR ALL TO authenticated USING (true) WITH CHECK (true);
CREATE POLICY authenticated_all ON public.critic_feedback
  FOR ALL TO authenticated USING (true) WITH CHECK (true);
