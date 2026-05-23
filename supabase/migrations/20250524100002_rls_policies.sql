-- Phase 2: RLS policies (single-tenant dispatcher app; auth wired in Phase 8).
-- Service role bypasses RLS. Authenticated dispatchers get read/write on ops tables.

-- Helper: drop policy if re-running migration during dev
DO $$
DECLARE
  t text;
  tables text[] := ARRAY[
    'clients', 'crews', 'equipment', 'crew_equipment', 'jobs',
    'crew_skills', 'service_history',
    'plans', 'crew_days', 'scheduled_stops'
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

-- Authenticated: full access for internal dispatcher (tighten per-role in Phase 8)
CREATE POLICY authenticated_all ON public.clients
  FOR ALL TO authenticated USING (true) WITH CHECK (true);

CREATE POLICY authenticated_all ON public.crews
  FOR ALL TO authenticated USING (true) WITH CHECK (true);

CREATE POLICY authenticated_all ON public.equipment
  FOR ALL TO authenticated USING (true) WITH CHECK (true);

CREATE POLICY authenticated_all ON public.crew_equipment
  FOR ALL TO authenticated USING (true) WITH CHECK (true);

CREATE POLICY authenticated_all ON public.crew_skills
  FOR ALL TO authenticated USING (true) WITH CHECK (true);

CREATE POLICY authenticated_all ON public.jobs
  FOR ALL TO authenticated USING (true) WITH CHECK (true);

CREATE POLICY authenticated_all ON public.service_history
  FOR ALL TO authenticated USING (true) WITH CHECK (true);

CREATE POLICY authenticated_all ON public.plans
  FOR ALL TO authenticated USING (true) WITH CHECK (true);

CREATE POLICY authenticated_all ON public.crew_days
  FOR ALL TO authenticated USING (true) WITH CHECK (true);

CREATE POLICY authenticated_all ON public.scheduled_stops
  FOR ALL TO authenticated USING (true) WITH CHECK (true);

-- Anon: read-only on non-sensitive ops data (optional public status page)
CREATE POLICY anon_read_clients ON public.clients
  FOR SELECT TO anon USING (true);

CREATE POLICY anon_read_jobs ON public.jobs
  FOR SELECT TO anon USING (status IN ('scheduled', 'confirmed'));
