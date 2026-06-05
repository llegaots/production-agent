-- ============================================================================
-- RouteIQ — Route generation PREVIEW + AI chat refine.
-- Generations now produce a reviewable preview (not committed routes); the
-- manager can chat to refine it, then Confirm to schedule. Run after 0001.
-- ============================================================================

-- Allow the two new lifecycle states.
alter table "D2D_RouteGenerations" drop constraint if exists "D2D_RouteGenerations_status_check";
alter table "D2D_RouteGenerations"
  add constraint "D2D_RouteGenerations_status_check"
  check (status in ('queued','running','preview','confirmed','done','error'));

-- The proposed routes (paths, doors, pairings, chat) shown for review, and the
-- cached street/home geometry so refinement re-plans without re-hitting OSM.
alter table "D2D_RouteGenerations" add column if not exists preview   jsonb;
alter table "D2D_RouteGenerations" add column if not exists geo_cache jsonb;
