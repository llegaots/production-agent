-- ============================================================================
-- RouteIQ - Persist the rep's walked GPS trail on the session, so the live trace
-- survives navigation/reload and can render on the overview cards (not just the
-- detail view). Downsampled point list, appended by the /position endpoint.
-- Run after 0006.
-- ============================================================================

alter table "D2D_Sessions" add column if not exists trail_path jsonb not null default '[]'::jsonb;
