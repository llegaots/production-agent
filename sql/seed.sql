-- Seed: West Island (Montreal) bookings — mirrors app/seed.py
-- For a fresh DB, run schema.sql first. To replace existing demo data, use west_island_jobs.sql.

insert into public.clients (id, name, contact_email, contact_phone, preferred_contact, notes) values
  ('cli_001', 'Jeff Clement',              '', '514-297-4807', 'phone', 'JOB-001'),
  ('cli_002', 'Sherif & Isabella Zalidia', '', '514-312-6060', 'phone', 'JOB-002'),
  ('cli_003', 'Claudia Schmidt',           '', '514-312-6060', 'phone', 'JOB-003 — same address as JOB-002'),
  ('cli_004', 'Jean Francois Fortin',      '', '514-433-4316', 'phone', 'JOB-004'),
  ('cli_005', 'Marilyn Spriggs',           '', '514-457-3342', 'phone', 'JOB-005'),
  ('cli_006', 'Helen Finn',                '', '514-266-7036', 'phone', 'JOB-006')
on conflict (id) do update set
  name = excluded.name,
  contact_phone = excluded.contact_phone,
  notes = excluded.notes;

insert into public.equipment (id, kind, label, quantity) values
  ('eq_pw_1',     'pressure_washer', 'Hot-water PW #1', 1),
  ('eq_pw_2',     'pressure_washer', 'Cold-water PW #2', 1),
  ('eq_wfp_1',    'water_fed_pole',  'Water-fed pole 40ft', 1),
  ('eq_wfp_2',    'water_fed_pole',  'Water-fed pole 25ft', 1),
  ('eq_lift_1',   'scissor_lift',    'Scissor lift (rental)', 1),
  ('eq_rope_1',   'rope_kit',        'Rope access kit A', 1),
  ('eq_ladder_1', 'ladder_28',       '28ft extension ladder', 1),
  ('eq_ladder_2', 'ladder_28',       '28ft extension ladder #2', 1),
  ('eq_ext_1',    'extension_pole',  'Eaves / soffit pole', 1),
  ('eq_van_1',    'van',             'Van Alpha', 1),
  ('eq_van_2',    'van',             'Van Bravo', 1),
  ('eq_van_3',    'van',             'Van Charlie', 1)
on conflict (id) do nothing;

insert into public.crews (id, name, members, skills, daily_minutes, base_lat, base_lng, hourly_cost) values
  ('crew_alpha',   'Alpha (Residential — West Island)', array['Marco','Tasha'],
     array['ladder_cert','pressure_wash'], 480, 45.4030, -73.9470, 110.00),
  ('crew_bravo',   'Bravo (Commercial — West Island)',  array['Devin','Pia','Luis'],
     array['ladder_cert','lift_operator','pressure_wash','glass_restoration'], 540, 45.4030, -73.9470, 180.00),
  ('crew_charlie', 'Charlie (High-rise — West Island)', array['Sam','Quinn'],
     array['rope_access','lift_operator','glass_restoration'], 480, 45.4030, -73.9470, 210.00)
on conflict (id) do update set
  name = excluded.name,
  base_lat = excluded.base_lat,
  base_lng = excluded.base_lng;

insert into public.crew_equipment (crew_id, equipment_id) values
  ('crew_alpha',   'eq_pw_2'),
  ('crew_alpha',   'eq_wfp_2'),
  ('crew_alpha',   'eq_ladder_1'),
  ('crew_alpha',   'eq_ext_1'),
  ('crew_alpha',   'eq_van_1'),
  ('crew_bravo',   'eq_pw_1'),
  ('crew_bravo',   'eq_wfp_1'),
  ('crew_bravo',   'eq_lift_1'),
  ('crew_bravo',   'eq_ladder_2'),
  ('crew_bravo',   'eq_ext_1'),
  ('crew_bravo',   'eq_van_2'),
  ('crew_charlie', 'eq_rope_1'),
  ('crew_charlie', 'eq_van_3')
on conflict do nothing;

insert into public.jobs (
  id, client_id, service_type, address, lat, lng,
  estimated_minutes, difficulty,
  required_skills, required_equipment,
  earliest_date, latest_date, price, status, notes
) values
  ('job_001','cli_001','window_cleaning','18 Simone-De Beauvoir, Notre-Dame-de-l''Île-Perrot QC J7V 8P4',45.3838,-73.8825,
     90, 2, array['ladder_cert'], array['ladder_28','water_fed_pole','van'],
     '2026-07-01','2026-07-31', 0,'pending','JOB-001 · Île-Perrot · Interior/Exterior Windows. Standard residential job. Unscheduled.'),
  ('job_002','cli_002','window_cleaning','9 Place Bastien, Pincourt QC J7W 7J2',45.3762,-73.9852,
     150, 3, array['ladder_cert','pressure_wash'], array['ladder_28','water_fed_pole','extension_pole','van'],
     '2026-07-01','2026-07-31', 0,'pending','JOB-002 · Pincourt · Windows + Eaves. Needs eaves; allow buffer. Unscheduled.'),
  ('job_003','cli_003','window_cleaning','9 Place Bastien, Pincourt QC J7W 7J2',45.3764,-73.9850,
     90, 2, array['ladder_cert'], array['ladder_28','water_fed_pole','van'],
     '2026-07-01','2026-07-31', 0,'pending','JOB-003 · Pincourt · Same address/area as JOB-002. Unscheduled.'),
  ('job_004','cli_004','window_cleaning','23 Rue Madore, Île-Perrot QC J7V 0B1',45.3810,-73.8780,
     150, 3, array['ladder_cert','pressure_wash'], array['ladder_28','water_fed_pole','extension_pole','van'],
     '2026-07-01','2026-07-31', 0,'pending','JOB-004 · Île-Perrot · Windows + Eaves. Verify preferred timing. Unscheduled.'),
  ('job_005','cli_005','gutter_cleaning','32 Oxford, Baie-D''Urfé QC H9X 2T5',45.4582,-73.9155,
     240, 4, array['ladder_cert','pressure_wash','lift_operator'], array['ladder_28','pressure_washer','water_fed_pole','scissor_lift','van'],
     '2026-08-15','2026-08-31', 0,'pending','JOB-005 · Baie-D''Urfé · Interior/Eaves/Soft cleaning/Gutter guard. Large job; do not overpack day. Unscheduled.'),
  ('job_006','cli_006','window_cleaning','99 Meloche, Sainte-Anne-de-Bellevue QC H9X 3Z5',45.4035,-73.9478,
     120, 2, array['ladder_cert','pressure_wash'], array['ladder_28','water_fed_pole','extension_pole','van'],
     '2026-07-01','2026-07-31', 0,'pending','JOB-006 · Sainte-Anne-de-Bellevue · Windows + Eaves. Group with Baie-D''Urfé / West Island jobs. Unscheduled.')
on conflict (id) do update set
  client_id = excluded.client_id,
  service_type = excluded.service_type,
  address = excluded.address,
  lat = excluded.lat,
  lng = excluded.lng,
  estimated_minutes = excluded.estimated_minutes,
  difficulty = excluded.difficulty,
  required_skills = excluded.required_skills,
  required_equipment = excluded.required_equipment,
  earliest_date = excluded.earliest_date,
  latest_date = excluded.latest_date,
  notes = excluded.notes,
  status = 'pending';
