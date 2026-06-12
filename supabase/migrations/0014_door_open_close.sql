-- ============================================================================
-- RouteIQ - Open/close door events.
-- A door row is now inserted the moment the rep dwells at a home
-- (status='open', address already resolved server-side) so leads detected
-- MID-conversation inherit the right home instantly, then the row is
-- finalized when the rep walks away (outcome classified, better fix kept).
-- Leads link to their door so the close phase can back-fill weaker addresses.
-- Run after 0012.
-- ============================================================================

alter table "D2D_DoorEvents"
  add column if not exists status text not null default 'closed'
    check (status in ('open', 'closed'));

-- Find leftover open doors fast (end-of-session sweep).
create index if not exists d2d_door_open_idx
  on "D2D_DoorEvents" (session_id) where status = 'open';

-- Lead -> door linkage (back-fill target). Undoing a door keeps the lead.
alter table "D2D_Leads"
  add column if not exists door_event_id uuid
    references "D2D_DoorEvents"(id) on delete set null;

create index if not exists d2d_leads_door_event_idx
  on "D2D_Leads" (door_event_id);
