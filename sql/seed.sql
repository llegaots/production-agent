-- Seed: ClearView Exterior Services in Austin
-- Same fictional dataset used by app/seed.py so the Supabase-backed run
-- produces the same plan as the in-memory demo.

insert into public.clients (id, name, contact_email, contact_phone, preferred_contact) values
  ('cli_001', 'Maple Ridge HOA',       'hoa@mapleridge.example',     '512-555-0101', 'email'),
  ('cli_002', 'Lake Travis Estate',    'owner@laketravis.example',   '512-555-0102', 'phone'),
  ('cli_003', 'Congress Tower LLC',    'ops@congresstower.example',  '512-555-0103', 'email'),
  ('cli_004', 'Pecan Street Bistro',   'manager@pecanbistro.example','512-555-0104', 'email'),
  ('cli_005', 'Soco Lofts',            'board@socolofts.example',    '512-555-0105', 'email'),
  ('cli_006', 'The Vance Residence',   'vance@example.com',          '512-555-0106', 'email'),
  ('cli_007', 'Bouldin Creek Cafe',    'hello@bouldincafe.example',  '512-555-0107', 'email'),
  ('cli_008', 'Domain Northside Mgmt', 'fm@domainnorth.example',     '512-555-0108', 'email'),
  ('cli_009', 'Zilker Bungalow',       'zb@example.com',             '512-555-0109', 'email'),
  ('cli_010', 'Mueller Medical Plaza', 'ops@muellermed.example',     '512-555-0110', 'email')
on conflict (id) do nothing;

insert into public.equipment (id, kind, label, quantity) values
  ('eq_pw_1',     'pressure_washer', 'Hot-water PW #1', 1),
  ('eq_pw_2',     'pressure_washer', 'Cold-water PW #2', 1),
  ('eq_wfp_1',    'water_fed_pole',  'Water-fed pole 40ft', 1),
  ('eq_wfp_2',    'water_fed_pole',  'Water-fed pole 25ft', 1),
  ('eq_lift_1',   'scissor_lift',    'Scissor lift (rental)', 1),
  ('eq_rope_1',   'rope_kit',        'Rope access kit A', 1),
  ('eq_ladder_1', 'ladder_28',       '28ft extension ladder', 1),
  ('eq_ladder_2', 'ladder_28',       '28ft extension ladder #2', 1),
  ('eq_van_1',    'van',             'Van Alpha', 1),
  ('eq_van_2',    'van',             'Van Bravo', 1),
  ('eq_van_3',    'van',             'Van Charlie', 1)
on conflict (id) do nothing;

insert into public.crews (id, name, members, skills, daily_minutes, base_lat, base_lng, hourly_cost) values
  ('crew_alpha',   'Alpha (Residential)', array['Marco','Tasha'],
     array['ladder_cert','pressure_wash'], 480, 30.2672, -97.7431, 110.00),
  ('crew_bravo',   'Bravo (Commercial)',  array['Devin','Pia','Luis'],
     array['ladder_cert','lift_operator','pressure_wash','glass_restoration'], 540, 30.2672, -97.7431, 180.00),
  ('crew_charlie', 'Charlie (High-rise)', array['Sam','Quinn'],
     array['rope_access','lift_operator','glass_restoration'], 480, 30.2672, -97.7431, 210.00)
on conflict (id) do nothing;

insert into public.crew_equipment (crew_id, equipment_id) values
  ('crew_alpha',   'eq_pw_2'),
  ('crew_alpha',   'eq_wfp_2'),
  ('crew_alpha',   'eq_ladder_1'),
  ('crew_alpha',   'eq_van_1'),
  ('crew_bravo',   'eq_pw_1'),
  ('crew_bravo',   'eq_wfp_1'),
  ('crew_bravo',   'eq_lift_1'),
  ('crew_bravo',   'eq_ladder_2'),
  ('crew_bravo',   'eq_van_2'),
  ('crew_charlie', 'eq_rope_1'),
  ('crew_charlie', 'eq_van_3')
on conflict do nothing;

with week_window as (
  select
    (current_date - ((extract(isodow from current_date)::int - 1)))::date as monday,
    (current_date - ((extract(isodow from current_date)::int - 1)))::date + 4 as friday
)
insert into public.jobs (
  id, client_id, service_type, address, lat, lng,
  estimated_minutes, difficulty,
  required_skills, required_equipment,
  earliest_date, latest_date, price, status, notes
)
select * from (values
  ('job_001','cli_001','window_cleaning','4501 Maple Ridge Dr, Austin, TX',30.3527,-97.7493,
     180, 2::smallint, array['ladder_cert'], array['water_fed_pole','ladder_28','van'],
     (select monday from week_window),(select friday from week_window), 620.00,'pending','20 townhomes, exterior only.'),
  ('job_002','cli_002','window_cleaning','22 Vista Trail, Lakeway, TX',30.3711,-97.9794,
     300, 4::smallint, array['ladder_cert','glass_restoration'], array['water_fed_pole','ladder_28','van'],
     (select monday from week_window),(select friday from week_window), 1850.00,'pending','Large lakefront home. Hard-water spotting on west elevation.'),
  ('job_003','cli_003','high_rise','100 Congress Ave, Austin, TX',30.2630,-97.7434,
     420, 5::smallint, array['rope_access','glass_restoration'], array['rope_kit','van'],
     (select monday from week_window),(select friday from week_window), 3400.00,'pending','High-rise rope descent. Building requires confirmed window 48h ahead.'),
  ('job_004','cli_004','pressure_washing','421 E 6th St, Austin, TX',30.2670,-97.7404,
     150, 2::smallint, array['pressure_wash'], array['pressure_washer','van'],
     (select monday from week_window),(select friday from week_window), 480.00,'pending','Sidewalk + patio. Must be done before 10am open.'),
  ('job_005','cli_005','window_cleaning','1500 S Congress Ave, Austin, TX',30.2517,-97.7497,
     240, 3::smallint, array['lift_operator','ladder_cert'], array['scissor_lift','van'],
     (select monday from week_window),(select friday from week_window), 980.00,'pending','Mixed-use loft building.'),
  ('job_006','cli_006','window_cleaning','3007 Westlake Dr, Austin, TX',30.2972,-97.8059,
     120, 2::smallint, array['ladder_cert'], array['water_fed_pole','ladder_28','van'],
     (select monday from week_window),(select friday from week_window), 420.00,'pending','Repeat customer, prefers mornings.'),
  ('job_007','cli_007','gutter_cleaning','1900 S 1st St, Austin, TX',30.2520,-97.7548,
     90,  2::smallint, array['ladder_cert'], array['ladder_28','van'],
     (select monday from week_window),(select friday from week_window), 280.00,'pending','Quick cleanout. Cafe closed Tuesdays.'),
  ('job_008','cli_008','window_cleaning','11801 Domain Blvd, Austin, TX',30.4012,-97.7253,
     360, 4::smallint, array['lift_operator','ladder_cert'], array['scissor_lift','van'],
     (select monday from week_window),(select friday from week_window), 1640.00,'pending','Storefront, requires after-hours lift access.'),
  ('job_009','cli_009','window_cleaning','2010 Bluebonnet Ln, Austin, TX',30.2625,-97.7689,
     90,  1::smallint, array['ladder_cert'], array['water_fed_pole','van'],
     (select monday from week_window),(select friday from week_window), 210.00,'pending',''),
  ('job_010','cli_010','solar_panel_cleaning','1801 East Dean Keeton, Austin, TX',30.2902,-97.7264,
     180, 3::smallint, array['lift_operator'], array['scissor_lift','van'],
     (select monday from week_window),(select friday from week_window), 720.00,'pending','Medical plaza rooftop array.')
) as v(
  id, client_id, service_type, address, lat, lng,
  estimated_minutes, difficulty,
  required_skills, required_equipment,
  earliest_date, latest_date, price, status, notes
)
on conflict (id) do nothing;
