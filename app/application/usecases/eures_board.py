"""Board for EURES collection — per COUNTRY (EURES is country-driven, not per-profession like
Careerjet/Jooble). Data is derived from the persisted postings (location = country code), so no
extra tally table is needed."""
from __future__ import annotations

import html as _html
from collections import Counter
from datetime import datetime

from sqlalchemy import func, select

from ...data.models import Posting

# EURES uses EU country codes — note EL = Greece (not GR).
_FLAG = {"BG": "🇧🇬", "RO": "🇷🇴", "EL": "🇬🇷", "GR": "🇬🇷", "PT": "🇵🇹", "IE": "🇮🇪", "SE": "🇸🇪",
         "DK": "🇩🇰", "FI": "🇫🇮", "CZ": "🇨🇿", "HU": "🇭🇺", "HR": "🇭🇷", "SK": "🇸🇰", "SI": "🇸🇮",
         "LT": "🇱🇹", "LV": "🇱🇻", "EE": "🇪🇪", "LU": "🇱🇺", "AT": "🇦🇹", "BE": "🇧🇪", "DE": "🇩🇪",
         "FR": "🇫🇷", "IT": "🇮🇹", "ES": "🇪🇸", "NL": "🇳🇱", "PL": "🇵🇱"}
_NAME = {"BG": "България", "RO": "Румъния", "EL": "Гърция", "GR": "Гърция", "PT": "Португалия",
         "IE": "Ирландия", "SE": "Швеция", "DK": "Дания", "FI": "Финландия", "CZ": "Чехия",
         "HU": "Унгария", "HR": "Хърватия", "SK": "Словакия", "SI": "Словения", "LT": "Литва",
         "LV": "Латвия", "EE": "Естония", "LU": "Люксембург"}


def status(db) -> dict:
    """Per-country EURES tallies + total, from the persisted postings."""
    rows = db.execute(
        select(Posting.location, func.count(Posting.id))
        .where(Posting.url.like("%eures%")).group_by(Posting.location)).all()
    per = Counter()
    for loc, n in rows:
        codes = [c.strip().upper() for c in (loc or "").split(",") if c.strip()]
        # keep only recognizable 2-letter country codes (drops noisy city strings)
        codes = [c for c in codes if len(c) == 2 and c.isalpha()]
        for c in codes:
            per[c] += n
    total = db.scalar(select(func.count(Posting.id)).where(Posting.url.like("%eures%"))) or 0
    return {"total": total, "countries": per.most_common()}


def render_board(st: dict, *, generated_at: datetime | None = None) -> str:
    gen = (generated_at or datetime.utcnow()).strftime("%Y-%m-%d %H:%M UTC")
    countries = st["countries"]
    top = max((n for _, n in countries), default=1) or 1
    rows = []
    for code, n in countries:
        pct = round(100 * n / top, 1)
        label = f"{_FLAG.get(code, '🇪🇺')} {_NAME.get(code, code)}"
        rows.append(
            f'<tr><td>{_html.escape(label)}</td><td class="num">{n:,}</td>'
            f'<td class="pg"><div class="bar"><span style="width:{pct:.1f}%"></span></div></td></tr>')
    return _TMPL.format(
        gen=gen, total=f"{st['total']:,}", ncountries=len(countries),
        rows="\n".join(rows) or '<tr><td colspan="3" class="muted">няма събрани обяви още</td></tr>')


_TMPL = """<title>EURES — collection by country</title>
<style>
  :root {{ --bg:#f6f7f9; --panel:#fff; --ink:#111823; --muted:#5b6675; --line:#e5e8ee;
    --accent:#003399; --track:#e4ebee; }}
  @media (prefers-color-scheme:dark) {{ :root {{ --bg:#0d1117; --panel:#161b22; --ink:#e8edf3;
    --muted:#8b96a5; --line:#232a34; --accent:#5b8dee; --track:#1d2c31; }} }}
  :root[data-theme="dark"] {{ --bg:#0d1117; --panel:#161b22; --ink:#e8edf3; --muted:#8b96a5;
    --line:#232a34; --accent:#5b8dee; --track:#1d2c31; }}
  :root[data-theme="light"] {{ --bg:#f6f7f9; --panel:#fff; --ink:#111823; --muted:#5b6675;
    --line:#e5e8ee; --accent:#003399; --track:#e4ebee; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }}
  .wrap {{ max-width:840px; margin:0 auto; padding:32px 24px 64px; }}
  .top {{ display:flex; align-items:baseline; justify-content:space-between; gap:16px; flex-wrap:wrap; }}
  h1 {{ font-size:22px; margin:0; letter-spacing:-.01em; }}
  h1 span {{ color:var(--muted); font-size:14px; font-weight:400; }}
  .sub {{ color:var(--muted); font-size:13px; }}
  .hero {{ background:var(--panel); border:1px solid var(--line); border-radius:14px;
    padding:22px; margin:18px 0 22px; display:flex; gap:32px; flex-wrap:wrap; }}
  .big {{ font-size:38px; font-weight:700; letter-spacing:-.02em; font-variant-numeric:tabular-nums;
    line-height:1; }}
  .big small {{ display:block; font-size:12px; color:var(--muted); font-weight:500; margin-top:6px;
    letter-spacing:.02em; }}
  .tablewrap {{ overflow-x:auto; background:var(--panel); border:1px solid var(--line);
    border-radius:12px; }}
  table {{ width:100%; border-collapse:collapse; font-size:13.5px; }}
  th,td {{ text-align:left; padding:9px 14px; border-bottom:1px solid var(--line); white-space:nowrap; }}
  th {{ font-size:11px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); }}
  tr:last-child td {{ border-bottom:none; }}
  td.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .muted {{ color:var(--muted); }}
  td.pg {{ width:280px; }}
  .bar {{ height:8px; background:var(--track); border-radius:5px; overflow:hidden; }}
  .bar span {{ display:block; height:100%; background:var(--accent); border-radius:5px; }}
</style>
<div class="wrap">
  <div class="top">
    <h1>EURES <span>· официалният ЕС портал · държавите, които другите пропускат</span></h1>
    <div class="sub">updated {gen}</div>
  </div>
  <div class="hero">
    <div class="big">{total}<small>ОБЯВИ СЪБРАНИ</small></div>
    <div class="big">{ncountries}<small>ДЪРЖАВИ</small></div>
  </div>
  <div class="tablewrap">
    <table>
      <thead><tr><th>Държава</th><th>Обяви</th><th>Дял</th></tr></thead>
      <tbody>
        {rows}
      </tbody>
    </table>
  </div>
</div>
"""
