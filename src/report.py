"""insights.html report generator — one self-contained HTML file per run.

Inline CSS, no external assets. Sections per PROJECT.md:
  1. Run summary  2. Ranked candidate table  3. Per-selected-stock cards
  4. Skipped/failed terms + unmatched live-ad-group lines (hygiene list).
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment

_env = Environment(autoescape=True)

TEMPLATE = _env.from_string("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>DEGIRO stock ads — insights {{ date }}</title>
<style>
  body { font-family: -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
         margin: 0; background: #f4f6f8; color: #1c2b39; }
  .wrap { max-width: 1080px; margin: 0 auto; padding: 24px; }
  h1 { font-size: 22px; } h2 { font-size: 17px; margin-top: 32px; }
  .summary { display: flex; flex-wrap: wrap; gap: 12px; }
  .stat { background: #fff; border: 1px solid #dde3e9; border-radius: 8px;
          padding: 10px 16px; min-width: 110px; }
  .stat .v { font-size: 20px; font-weight: 700; color: #0a4a8f; }
  .stat .k { font-size: 11px; text-transform: uppercase; letter-spacing: .05em; color: #5b6b7b; }
  table { border-collapse: collapse; width: 100%; background: #fff;
          border: 1px solid #dde3e9; border-radius: 8px; overflow: hidden; }
  th, td { text-align: left; padding: 7px 10px; font-size: 13px; border-top: 1px solid #eef1f4; }
  th { background: #eef3f8; border-top: none; font-size: 12px; }
  .badge { display: inline-block; font-size: 11px; font-weight: 600; border-radius: 10px;
           padding: 1px 9px; }
  .live { background: #e8eef4; color: #45596d; }
  .selected { background: #d9efe0; color: #176639; }
  .card { background: #fff; border: 1px solid #dde3e9; border-radius: 8px;
          padding: 16px 18px; margin: 14px 0; }
  .card h3 { margin: 0 0 4px; font-size: 16px; }
  .meta { font-size: 12px; color: #5b6b7b; margin-bottom: 10px; }
  .chars { color: #5b6b7b; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .chars.max { color: #b3640a; font-weight: 600; }
  .pos { color: #0a4a8f; font-weight: 600; }
  .kw { display: inline-block; background: #eef3f8; border-radius: 4px;
        padding: 2px 8px; margin: 2px; font-size: 12px; }
  .warn { background: #fdf3e1; border-left: 3px solid #e3a008; padding: 6px 10px;
          font-size: 12px; margin: 4px 0; }
  .error { background: #fbe9e9; border-left: 3px solid #c0392b; padding: 6px 10px;
           font-size: 13px; margin: 4px 0; }
  .drop { color: #8a97a5; font-size: 12px; font-style: italic; }
  .empty { color: #aab4be; }
  details { margin: 8px 0; } summary { cursor: pointer; font-size: 13px; color: #0a4a8f; }
  ul.plain { margin: 6px 0; padding-left: 20px; font-size: 13px; }
  footer { margin: 36px 0 12px; font-size: 11px; color: #8a97a5; }
</style>
</head>
<body><div class="wrap">

<h1>DEGIRO stock ads — run {{ date }}</h1>

{% if errors %}
<h2>Build failed — {{ errors|length }} validation error(s)</h2>
{% for e in errors %}<div class="error">{{ e }}</div>{% endfor %}
{% endif %}

<h2>Run summary</h2>
<div class="summary">
  <div class="stat"><div class="v">{{ provider_used }}</div><div class="k">provider</div></div>
  <div class="stat"><div class="v">{{ universe_size }}</div><div class="k">universe</div></div>
  <div class="stat"><div class="v">{{ candidates|length }}</div><div class="k">candidates</div></div>
  <div class="stat"><div class="v">{{ n_live }}</div><div class="k">already live</div></div>
  <div class="stat"><div class="v">{{ n_selected }}</div><div class="k">selected</div></div>
  <div class="stat"><div class="v">{{ threshold }}</div><div class="k">threshold</div></div>
</div>
{% if provider_used != provider_requested %}
<div class="warn">Fallback triggered: provider <b>{{ provider_requested }}</b> requested,
<b>{{ provider_used }}</b> used.</div>
{% endif %}

<h2>Ranked candidates</h2>
<table>
<tr><th>#</th><th>Ticker</th><th>Name</th><th>Score</th><th>Δ vs baseline</th><th></th></tr>
{% for c in candidates %}
<tr>
  <td>{{ loop.index }}</td>
  <td><b>{{ c.ticker }}</b></td>
  <td>{{ c.name }}</td>
  <td>{{ "%.0f"|format(c.score) }}</td>
  <td>{% if c.delta_pct is not none %}{{ "%+.0f%%"|format(c.delta_pct) }}{% else %}&mdash;{% endif %}</td>
  <td>
    {% if c.already_live %}<span class="badge live">LIVE</span>{% endif %}
    {% if c.selected %}<span class="badge selected">SELECTED</span>{% endif %}
  </td>
</tr>
{% endfor %}
</table>

{% if cards %}<h2>Generated ads ({{ cards|length }})</h2>{% endif %}
{% for card in cards %}
<div class="card">
  <h3>{{ card.ad_group }} <span class="meta">({{ card.ticker }})</span></h3>
  <div class="meta">score {{ "%.0f"|format(card.score) }}
    {% if card.delta_pct is not none %} · Δ {{ "%+.0f%%"|format(card.delta_pct) }}{% endif %}
    · term “{{ card.best_term }}” · {{ card.final_url }} · /{{ card.path1 }}/{{ card.path2 }}</div>

  <table>
  <tr><th>Headline</th><th>Text</th><th>Chars</th><th>Pin</th></tr>
  {% for h in card.headlines %}
  <tr>
    <td>{{ h.slot }}</td>
    <td>{% if h.text %}{{ h.text }}{% else %}<span class="empty">(dropped)</span>{% endif %}</td>
    <td class="chars{% if h.chars == h.limit %} max{% endif %}">{% if h.text %}{{ h.chars }}/{{ h.limit }}{% endif %}</td>
    <td>{% if h.position and h.position != "--" %}<span class="pos">{{ h.position }}</span>{% else %}&ndash;{% endif %}</td>
  </tr>
  {% endfor %}
  {% for d in card.descriptions %}
  <tr>
    <td>D{{ d.slot }}</td>
    <td>{{ d.text }}</td>
    <td class="chars{% if d.chars == d.limit %} max{% endif %}">{{ d.chars }}/{{ d.limit }}</td>
    <td>{% if d.position and d.position != "--" %}<span class="pos">{{ d.position }}</span>{% else %}&ndash;{% endif %}</td>
  </tr>
  {% endfor %}
  </table>

  <div style="margin-top:10px">
  {% for kw in card.keywords %}<span class="kw">{{ kw }}</span>{% endfor %}
  <span class="meta">(each as Exact + Phrase)</span>
  </div>

  {% for w in card.warnings %}<div class="warn">{{ w }}</div>{% endfor %}
  {% for d in card.dropped %}<div class="drop">{{ d }}</div>{% endfor %}
</div>
{% endfor %}

<h2>Operator hygiene</h2>
{% if unmatched %}
<div class="warn"><b>{{ unmatched|length }} live ad group line(s) matched nothing in the universe</b>
— fix the line or extend stock_universe.csv:</div>
<ul class="plain">{% for u in unmatched %}<li>{{ u }}</li>{% endfor %}</ul>
{% else %}
<p style="font-size:13px">All live ad group lines resolved against the universe.</p>
{% endif %}

{% if no_signal %}
<details><summary>{{ no_signal|length }} term(s) with no signal / failed</summary>
<ul class="plain">{% for t in no_signal %}<li>{{ t }}</li>{% endfor %}</ul>
</details>
{% endif %}

<footer>Generated by the DEGIRO stock-trend pipeline · provider {{ provider_used }}
· {{ date }}</footer>
</div></body></html>
""")


def render_report(path: str | Path, context: dict) -> Path:
    path = Path(path)
    path.write_text(TEMPLATE.render(**context), encoding="utf-8")
    return path
