-- ============================================================================
-- RouteIQ — Playbook (script + objections the AI agents grade against).
-- Run after 0001.
-- ============================================================================

create table if not exists "D2D_Playbooks" (
  id               uuid primary key default gen_random_uuid(),
  team_id          uuid references "D2D_Teams"(id) on delete cascade unique,
  script_title     text not null default 'Cold Approach Script',
  script           text not null default '',
  objections       jsonb not null default '[]'::jsonb,
  grading_criteria jsonb not null default '[]'::jsonb,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

alter table "D2D_Playbooks" enable row level security;
drop policy if exists "read_all" on "D2D_Playbooks";
create policy "read_all" on "D2D_Playbooks" for select using (true);
