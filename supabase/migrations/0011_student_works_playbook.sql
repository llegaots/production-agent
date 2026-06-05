-- ============================================================================
-- RouteIQ - Swap the demo company + playbook to STUDENT WORKS (painting).
-- Safe to re-run. Paste the whole file into the Supabase SQL editor.
--   - renames the team (company info)
--   - replaces the playbook script, objection handles, and grading criteria
--   - relabels any CrystalClear demo routes
-- Run after 0001/0004 (Teams + Playbooks must exist).
-- ============================================================================

do $$
declare
  v_team uuid;
begin
  -- 1. Company info: rename the (first) team to Student Works.
  select id into v_team from "D2D_Teams" order by created_at asc limit 1;
  if v_team is null then
    insert into "D2D_Teams"(name) values ('Student Works Painting') returning id into v_team;
  else
    update "D2D_Teams" set name = 'Student Works Painting' where id = v_team;
  end if;

  -- 2. Playbook: script + objection handles + grading criteria.
  insert into "D2D_Playbooks"(team_id, script_title, script, objections, grading_criteria)
  values (
    v_team,
    'Student Works - Canvassing Script',
    $script$OPENER (keep it light, 6 quick points)
"Hey, happy {weekday}! How's it going?"
1. Greeting.
2. Your name + school: "My name is {name}, I'm a student at {school}."
3. Who you're with: "This is our 3rd year running our business here in {city/area}."
4. Neighbour reference: "I was just speaking with your neighbour {neighbour}..."
5. The offer (below).
6. An open-ended question that starts with "what" (below).

THE OFFER
"We're in the neighbourhood offering FREE ESTIMATES for interior and exterior
painting and staining, as well as window cleaning and eavestrough cleaning."

OPEN-ENDED QUESTION (must start with "what")
"What projects could we take off your hands this year?"

MINDSET
- An objection is a "Yes, but...": yes I have a project, but I don't want you to do it.
- We are not here to change minds. We just want to get in front of the people already
  thinking about painting, staining, window or eavestrough cleaning.
- Wherever a step says "IF YES", you do not actually let them say yes. Handle the
  objection, then go straight into: "What was your name again, sorry?"

OBJECTIONS (acknowledge and ignore, reframe, then ask for the estimate)
Handle each of: "I do all my own painting", "I did all my painting last year",
"We don't have anything to paint", "I already have a painter", "It's too early to
make decisions", "We don't want to use students".
- IF NO: "No worries, can I follow up with you later in the spring or summer?" If still
  no, give a flyer, and get the name for the next door: "Sorry, I didn't catch your name?"
- IF YES: "What was your name again, sorry?" Look down at the clipboard and do not look
  up until they give you all the info. Give the flyer. "Jimmy will be reaching out in the
  next few days. Have a great day!"

HOW TO HANDLE A YES
- Do not show excitement. Stay level headed and collect everything (it shows
  professionalism). Celebrate once you're back in the car.
- Collect: name, at least 2 numbers (home, cell, work, partner's) -
  "What's another number I can reach you at in case I can't get you?", email, and the
  best time of day to call.

ASKING FOR A LAWN SIGN (a friendly homeowner on a busy street, after they decline)
"I understand. If I told you there was a way to help me out that wouldn't cost you
anything, would you be open to it?"
"I'm a student so my marketing budget is limited, and your house gets a lot of traffic.
If you'd let me put a lawn sign on your property for the first 2 weeks of April, it would
generate work for my crew without you doing anything. Would that be ok?"
"Perfect. The sign is expensive for me so I'll pick it up within 2 weeks. If you change
your mind, call the number on the sign and I'll grab it within 48 hours. Thanks again!"$script$,
    $obj$[
      {"id":"obj-diy","trigger":"I do all my own painting","category":"need","handle":"Acknowledge and ignore: 'Amazing, where do you find the time?' Then: 'Wouldn't it make sense to book a free estimate just to see if it makes sense for us to take the project off your hands?' If no, offer a spring or summer follow up; if still no, leave a flyer. Either way capture the name for the next door.","frequency":48,"successRate":41},
      {"id":"obj-last-year","trigger":"I did all my painting last year","category":"need","handle":"Acknowledge: 'Amazing, what work did you get done last year?' Then surface what they did NOT mention: 'A lot of your neighbours needed work on their (item they didn't mention), when did you last think about that?' Propose a free estimate. If no, follow up later or leave a flyer, and capture the name.","frequency":39,"successRate":44},
      {"id":"obj-nothing","trigger":"We don't have anything to paint","category":"need","handle":"Acknowledge: 'Got it, when did you last paint, interior or exterior?' Mention neighbours taking care of the opposite (whichever they didn't say), then ask when they last considered it. Propose a free estimate. If no, follow up later or leave a flyer, and capture the name.","frequency":52,"successRate":38},
      {"id":"obj-have-painter","trigger":"I already have a painter","category":"trust","handle":"Acknowledge: 'Fantastic, what were you planning to have them paint this year?' If they name a project: 'A lot of your neighbours have their own painter too, but most loved giving students a shot, especially since we have multiple teams and can start earlier in the season.' Brief pause, then propose a free estimate. If no, follow up later or leave a flyer, and capture the name.","frequency":33,"successRate":46},
      {"id":"obj-too-early","trigger":"It's too early to make decisions","category":"timing","handle":"Reframe: 'Now is actually the best time to book, you can check it off your list, and the only way to guarantee early-summer work is to book now. We also have a 10% early-season special.' Then ask what projects they're considering. If a project, propose a free estimate. If no, follow up later or leave a flyer, and capture the name.","frequency":44,"successRate":52},
      {"id":"obj-no-students","trigger":"We don't want to use students","category":"trust","handle":"Acknowledge: 'I completely get it, as young professionals we have a lot to prove. We go through expert training, our name is on the line, and referrals from quality work are how we grow.' Then: 'Let's schedule an estimate, and if we don't completely blow you away, I wouldn't want you to book with us.' If no, ask to follow up in spring, and capture the name.","frequency":18,"successRate":49}
    ]$obj$::jsonb,
    $crit$[
      {"id":"opener","label":"Opener & rapport","weight":20,"description":"Warm greeting, gives their name and school, mentions it's the 3rd year of the business in the area, and references a neighbour."},
      {"id":"offer","label":"Offer clarity","weight":15,"description":"Clearly states FREE estimates for interior and exterior painting and staining, plus window and eavestrough cleaning."},
      {"id":"discovery","label":"Open-ended question","weight":15,"description":"Asks an open-ended question starting with 'what' about projects, e.g. 'What projects could we take off your hands this year?'"},
      {"id":"objections","label":"Objection handling","weight":30,"description":"Acknowledges and ignores the objection, reframes using neighbours and value, asks to book a free estimate, and offers a follow up or flyer on a no."},
      {"id":"close","label":"Close & info capture","weight":20,"description":"On a yes, stays composed (no over-excitement) and collects the name, at least 2 phone numbers, email, and best time to call."}
    ]$crit$::jsonb
  )
  on conflict (team_id) do update set
    script_title     = excluded.script_title,
    script           = excluded.script,
    objections       = excluded.objections,
    grading_criteria = excluded.grading_criteria,
    updated_at       = now();

  -- 3. Relabel any CrystalClear demo routes to Student Works.
  update "D2D_Routes" set name = replace(name, 'CrystalClear', 'Student Works')
   where name like '%CrystalClear%';
end $$;
