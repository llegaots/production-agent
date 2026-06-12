-- ============================================================================
-- RouteIQ - Address accuracy + confidence. Door pins and leads now record the
-- raw GPS fix, its reported accuracy, the rooftop-snapped coordinate, and how
-- trustworthy the resolved street address is. Powers the CRM "needs address
-- check" safety net for fully-automatic capture. Safe to re-run.
-- Run after 0008 (door events) and 0007 (leads).
-- ============================================================================

-- ── Door events ─────────────────────────────────────────────────────────────
-- `lat`/`lng` stay the display pin (snapped when we trust it, else the GPS fix).
alter table "D2D_DoorEvents"
  add column if not exists gps_lat            double precision,
  add column if not exists gps_lng            double precision,
  add column if not exists gps_accuracy_m     double precision,
  add column if not exists snapped_lat        double precision,
  add column if not exists snapped_lng        double precision,
  add column if not exists address_source     text,   -- 'google' | 'nominatim' | 'gps'
  add column if not exists address_confidence text
    default 'gps-only'
    check (address_confidence in ('rooftop','interpolated','gps-only'));

-- ── Leads ───────────────────────────────────────────────────────────────────
-- A lead inherits its address (and confidence) from the door it was captured at.
-- `address_verified` flips true once a manager confirms/edits it in the CRM.
alter table "D2D_Leads"
  add column if not exists gps_accuracy_m     double precision,
  add column if not exists address_source     text,
  add column if not exists address_confidence text
    default 'gps-only'
    check (address_confidence in ('rooftop','interpolated','gps-only')),
  add column if not exists address_verified   boolean not null default false;

-- Manually-added CRM leads are entered by hand, so treat them as verified.
update "D2D_Leads"
  set address_confidence = 'rooftop', address_verified = true
  where source = 'manual' and address_verified = false;

-- Surface low-confidence, unverified leads for quick review.
create index if not exists d2d_leads_addr_check_idx
  on "D2D_Leads" (address_verified, address_confidence);
