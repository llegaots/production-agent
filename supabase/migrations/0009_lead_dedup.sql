-- ============================================================================
-- RouteIQ — Race-proof lead dedup. Concurrent detection passes (the live pass +
-- the end-of-session sweep) could both insert the same prospect before either
-- committed. A per-session unique key on phone-or-name makes that impossible.
-- Run after 0007.
-- ============================================================================

-- Stable identity within a session: digits of the phone if present, else the
-- normalized name. Immutable expression → allowed in a stored generated column.
alter table "D2D_Leads"
  add column if not exists dedup_key text generated always as (
    coalesce(
      nullif(regexp_replace(coalesce(phone, ''), '\D', '', 'g'), ''),
      lower(trim(name))
    )
  ) stored;

-- Remove any existing intra-session duplicates (keeps the earliest row), so the
-- unique index below can be created. Only touches session-scoped (auto-detected)
-- leads; manually-added CRM leads (session_id null) are left alone.
delete from "D2D_Leads" a
using "D2D_Leads" b
where a.session_id is not null
  and a.session_id = b.session_id
  and a.dedup_key = b.dedup_key
  and a.ctid > b.ctid;

-- One lead per (session, person). Partial so manual leads aren't constrained.
create unique index if not exists d2d_leads_session_dedup_uidx
  on "D2D_Leads" (session_id, dedup_key)
  where session_id is not null;
