"""Build a self-contained HTML report from a RunOptimizerOutput."""

from __future__ import annotations

import html
import json
from datetime import date
from typing import Any

from app.optimizer.models import OptimizerResult
from app.tools.schemas import RunOptimizerOutput


def _fmt_minute(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def build_optimizer_html_report(
    *,
    opt: RunOptimizerOutput,
    target_date: date,
    job_meta: dict[str, dict[str, Any]],
    crew_meta: dict[str, dict[str, Any]],
    equipment_check: dict[str, Any] | None = None,
    title: str = "Optimizer schedule preview",
) -> str:
    """Return HTML string for browser viewing."""
    result: OptimizerResult = opt.result
    assigned = len(result.assigned_job_ids)
    total = assigned + len(result.unassigned_job_ids)
    day_label = target_date.strftime("%A, %b %d, %Y")

    routes_html: list[str] = []
    timeline_html: list[str] = []

    for route in result.routes:
        if not route.stops:
            continue
        crew = crew_meta.get(route.crew_id, {})
        crew_name = crew.get("name") or route.crew_id
        shift_end = int(crew.get("shift_end_minute") or 480)
        shift_start = int(crew.get("shift_start_minute") or 0)
        span = max(shift_end - shift_start, 1)

        stops_li: list[str] = []
        bars: list[str] = []
        for idx, stop in enumerate(route.stops):
            job = job_meta.get(stop.job_id, {})
            addr = job.get("address") or ""
            skills = ", ".join(job.get("required_skills") or [])
            prev = route.stops[idx - 1] if idx > 0 else None
            drive = stop.arrival_minute - prev.depart_minute if prev else 0
            if drive > 0:
                stops_li.append(
                    f'<li class="drive">↳ {_esc(str(drive))} min drive</li>'
                )
            stops_li.append(
                f'<li class="stop">'
                f'<strong>{_esc(stop.job_id)}</strong>'
                f'{"<br><span class=\"muted\">" + _esc(addr) + "</span>" if addr else ""}'
                f'<br><span class="muted">Arrive {_fmt_minute(stop.arrival_minute)} · '
                f"Work until {_fmt_minute(stop.depart_minute)}</span>"
                f'{"<br><span class=\"tag\">" + _esc(skills) + "</span>" if skills else ""}'
                f"</li>"
            )
            left_pct = ((stop.arrival_minute - shift_start) / span) * 100
            width_pct = max(((stop.depart_minute - stop.arrival_minute) / span) * 100, 2)
            bars.append(
                f'<div class="bar" style="left:{left_pct:.1f}%;width:{width_pct:.1f}%" '
                f'title="{_esc(stop.job_id)} {_fmt_minute(stop.arrival_minute)}–{_fmt_minute(stop.depart_minute)}">'
                f"{_esc(stop.job_id.split('-')[-1][:12])}</div>"
            )

        routes_html.append(
            f"<tr><td class=\"crew\">"
            f"<strong>{_esc(crew_name)}</strong><br>"
            f'<span class="muted">{_esc(route.crew_id)}</span><br>'
            f'<span class="muted">{route.total_travel_minutes}m drive · '
            f"{route.total_service_minutes}m work</span>"
            f"</td><td><ol class=\"stops\">{''.join(stops_li)}</ol></td></tr>"
        )
        timeline_html.append(
            f'<div class="timeline-row">'
            f'<div class="timeline-label">{_esc(crew_name)}</div>'
            f'<div class="timeline-track">'
            f'<span class="axis">{_fmt_minute(shift_start)}</span>'
            f"{''.join(bars)}"
            f'<span class="axis end">{_fmt_minute(shift_end)}</span>'
            f"</div></div>"
        )

    if not routes_html:
        routes_html.append(
            '<tr><td colspan="2" class="empty">No routes — optimizer assigned no jobs to any crew.</td></tr>'
        )

    unassigned = result.unassigned_job_ids
    unassigned_html = ""
    if unassigned:
        items = []
        for jid in unassigned:
            job = job_meta.get(jid, {})
            skills = ", ".join(job.get("required_skills") or [])
            equip = ", ".join(job.get("required_equipment") or [])
            items.append(
                f"<li><code>{_esc(jid)}</code>"
                f'{" — " + _esc(job.get("address") or "") if job.get("address") else ""}'
                f'{"<br><span class=\"muted\">skills: " + _esc(skills) + "</span>" if skills else ""}'
                f'{" · equipment: " + _esc(equip) if equip else ""}'
                f"</li>"
            )
        unassigned_html = f'<section class="card warn"><h2>Unassigned ({len(unassigned)})</h2><ul>{"".join(items)}</ul></section>'

    messages_html = ""
    if result.messages:
        msgs = "".join(f"<li>{_esc(m)}</li>" for m in result.messages)
        messages_html = f'<section class="card"><h2>Optimizer messages</h2><ul>{msgs}</ul></section>'

    equip_html = ""
    if equipment_check:
        equip_html = (
            '<section class="card"><h2>Equipment check</h2>'
            f'<pre class="json">{_esc(json.dumps(equipment_check, indent=2, default=str))}</pre></section>'
        )

    status_class = "ok" if result.is_success else "bad"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{_esc(title)} — {_esc(day_label)}</title>
  <style>
    :root {{
      --bg: #0f1419;
      --card: #1a2332;
      --text: #e7ecf3;
      --muted: #8b9cb3;
      --accent: #3b82f6;
      --ok: #22c55e;
      --warn: #f59e0b;
      --bad: #ef4444;
      --bar: #2563eb;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      font-family: ui-sans-serif, system-ui, -apple-system, sans-serif;
      background: var(--bg);
      color: var(--text);
      margin: 0;
      padding: 1.5rem;
      line-height: 1.5;
    }}
    h1 {{ margin: 0 0 0.25rem; font-size: 1.5rem; }}
    .sub {{ color: var(--muted); margin-bottom: 1.5rem; }}
    .stats {{
      display: flex; flex-wrap: wrap; gap: 1rem;
      margin-bottom: 1.5rem;
    }}
    .stat {{
      background: var(--card);
      border-radius: 8px;
      padding: 0.75rem 1rem;
      min-width: 120px;
    }}
    .stat strong {{ display: block; font-size: 1.25rem; }}
    .stat span {{ color: var(--muted); font-size: 0.85rem; }}
    .badge {{
      display: inline-block;
      padding: 0.2rem 0.6rem;
      border-radius: 999px;
      font-size: 0.8rem;
      font-weight: 600;
      text-transform: uppercase;
    }}
    .badge.{status_class} {{
      background: {"rgba(34,197,94,0.2)" if result.is_success else "rgba(239,68,68,0.2)"};
      color: {"var(--ok)" if result.is_success else "var(--bad)"};
    }}
    .card {{
      background: var(--card);
      border-radius: 10px;
      padding: 1rem 1.25rem;
      margin-bottom: 1rem;
    }}
    .card.warn {{ border-left: 4px solid var(--warn); }}
    .card h2 {{ margin: 0 0 0.75rem; font-size: 1rem; }}
    table.routes {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.9rem;
    }}
    table.routes th, table.routes td {{
      border-bottom: 1px solid #2d3a4f;
      padding: 0.75rem;
      vertical-align: top;
      text-align: left;
    }}
    table.routes th {{ color: var(--muted); font-weight: 600; }}
    td.crew {{ width: 200px; white-space: nowrap; }}
    ol.stops {{ margin: 0; padding-left: 1.25rem; }}
    ol.stops li {{ margin-bottom: 0.5rem; }}
    ol.stops li.drive {{ color: var(--muted); list-style: none; margin-left: -1rem; }}
    .muted {{ color: var(--muted); font-size: 0.85rem; }}
    .tag {{ font-size: 0.75rem; color: var(--accent); }}
    .empty {{ text-align: center; color: var(--muted); padding: 2rem; }}
    .timeline-row {{
      display: grid;
      grid-template-columns: 140px 1fr;
      gap: 0.75rem;
      align-items: center;
      margin-bottom: 0.75rem;
    }}
    .timeline-label {{ font-size: 0.85rem; font-weight: 600; }}
    .timeline-track {{
      position: relative;
      height: 36px;
      background: #0d1117;
      border-radius: 6px;
      border: 1px solid #2d3a4f;
    }}
    .timeline-track .axis {{
      position: absolute;
      top: -1.4rem;
      font-size: 0.7rem;
      color: var(--muted);
    }}
    .timeline-track .axis.end {{ right: 0; left: auto; }}
    .timeline-track .bar {{
      position: absolute;
      top: 4px;
      height: 28px;
      background: var(--bar);
      border-radius: 4px;
      font-size: 0.65rem;
      overflow: hidden;
      white-space: nowrap;
      padding: 2px 4px;
      color: #fff;
    }}
    pre.json {{
      font-size: 0.75rem;
      overflow-x: auto;
      color: var(--muted);
      margin: 0;
    }}
    code {{ font-size: 0.85em; }}
  </style>
</head>
<body>
  <h1>{_esc(title)}</h1>
  <p class="sub">{_esc(day_label)} · <span class="badge {status_class}">{_esc(result.status)}</span></p>

  <div class="stats">
    <div class="stat"><strong>{assigned}</strong><span>jobs assigned</span></div>
    <div class="stat"><strong>{len(unassigned)}</strong><span>unassigned</span></div>
    <div class="stat"><strong>{len([r for r in result.routes if r.stops])}</strong><span>crews used</span></div>
    <div class="stat"><strong>{total}</strong><span>jobs in run</span></div>
  </div>

  <section class="card">
    <h2>Day timeline (by crew)</h2>
    {''.join(timeline_html) if timeline_html else '<p class="muted">No scheduled stops.</p>'}
  </section>

  <section class="card">
    <h2>Routes</h2>
    <table class="routes">
      <thead><tr><th>Crew</th><th>Stops</th></tr></thead>
      <tbody>{''.join(routes_html)}</tbody>
    </table>
  </section>

  {unassigned_html}
  {messages_html}
  {equip_html}
</body>
</html>"""
