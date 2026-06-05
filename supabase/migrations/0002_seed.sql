-- ============================================================================
-- Seed: one team + 4 marketers + a shift today for each (idempotent).
-- ============================================================================

insert into "D2D_Teams"(id, name) values
  ('d2d70000-0000-0000-0000-000000000001', 'Apex Exteriors — Toronto')
on conflict (id) do nothing;

insert into "D2D_Marketers"(id, team_id, name, email, phone, avatar_tint, status, home_territory, joined_at) values
  ('d2d70000-0000-0000-0000-0000000000a1', 'd2d70000-0000-0000-0000-000000000001', 'Marcus Bell',    'marcus@apexex.co',  '(416) 555-0142', 'emerald', 'offline', 'Leslieville',      '2024-08-12'),
  ('d2d70000-0000-0000-0000-0000000000a2', 'd2d70000-0000-0000-0000-000000000001', 'Sofia Reyes',     'sofia@apexex.co',   '(416) 555-0177', 'sky',     'offline', 'The Annex',        '2024-09-03'),
  ('d2d70000-0000-0000-0000-0000000000a3', 'd2d70000-0000-0000-0000-000000000001', 'DeShawn Carter',  'deshawn@apexex.co', '(416) 555-0259', 'violet',  'offline', 'Riverdale',        '2025-01-20'),
  ('d2d70000-0000-0000-0000-0000000000a4', 'd2d70000-0000-0000-0000-000000000001', 'Amara Okafor',    'amara@apexex.co',   '(416) 555-0288', 'amber',   'offline', 'Liberty Village',  '2025-02-14')
on conflict (id) do nothing;

-- A shift today (16:00–21:00) for each marketer so the generator has scheduled inputs.
insert into "D2D_Shifts"(id, marketer_id, date, start_time, end_time, status) values
  ('d2d70000-0000-0000-0000-0000000000b1', 'd2d70000-0000-0000-0000-0000000000a1', current_date, '16:00', '21:00', 'scheduled'),
  ('d2d70000-0000-0000-0000-0000000000b2', 'd2d70000-0000-0000-0000-0000000000a2', current_date, '16:00', '21:00', 'scheduled'),
  ('d2d70000-0000-0000-0000-0000000000b3', 'd2d70000-0000-0000-0000-0000000000a3', current_date, '17:00', '21:00', 'scheduled'),
  ('d2d70000-0000-0000-0000-0000000000b4', 'd2d70000-0000-0000-0000-0000000000a4', current_date, '17:00', '21:00', 'scheduled')
on conflict (id) do nothing;
