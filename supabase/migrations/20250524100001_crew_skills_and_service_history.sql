-- Phase 2: normalized crew skills + customer service history

-- PostGIS point on jobs (add if missing on existing databases)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'jobs' AND column_name = 'location'
  ) THEN
    ALTER TABLE public.jobs
      ADD COLUMN location geography(Point, 4326)
      GENERATED ALWAYS AS (
        ST_SetSRID(ST_MakePoint(lng, lat), 4326)::geography
      ) STORED;
    CREATE INDEX IF NOT EXISTS jobs_location_idx ON public.jobs USING GIST (location);
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- crew_skills (normalized from crews.skills[])
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.crew_skills (
  crew_id text NOT NULL REFERENCES public.crews (id) ON DELETE CASCADE,
  skill text NOT NULL,
  PRIMARY KEY (crew_id, skill)
);

COMMENT ON TABLE public.crew_skills IS
  'Normalized crew capabilities. Kept in sync with crews.skills for the optimizer.';

INSERT INTO public.crew_skills (crew_id, skill)
SELECT c.id, unnest(c.skills)
FROM public.crews c
WHERE cardinality(c.skills) > 0
ON CONFLICT (crew_id, skill) DO NOTHING;

-- ---------------------------------------------------------------------------
-- service_history (completed visits per customer)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.service_history (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id text NOT NULL REFERENCES public.clients (id) ON DELETE CASCADE,
  job_id text REFERENCES public.jobs (id) ON DELETE SET NULL,
  crew_id text REFERENCES public.crews (id) ON DELETE SET NULL,
  service_type text,
  completed_at timestamptz NOT NULL DEFAULT now(),
  notes text NOT NULL DEFAULT '',
  rating smallint CHECK (rating IS NULL OR (rating BETWEEN 1 AND 5)),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS service_history_client_id_idx
  ON public.service_history (client_id, completed_at DESC);

COMMENT ON TABLE public.service_history IS
  'Historical completed services per customer for CRM and scheduling context.';

ALTER TABLE public.crew_skills ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.service_history ENABLE ROW LEVEL SECURITY;

-- Product spec alias: customers → clients
CREATE OR REPLACE VIEW public.customers
WITH (security_invoker = true)
AS
SELECT
  id,
  name,
  contact_email AS email,
  contact_phone AS phone,
  preferred_contact,
  notes,
  created_at,
  updated_at
FROM public.clients;

COMMENT ON VIEW public.customers IS
  'Read-only alias for clients (customer-facing name in the product spec).';
