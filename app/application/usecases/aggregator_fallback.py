"""Aggregator fallback — keep collecting via Careerjet + Jooble when Adzuna is rate-limited.

Adzuna's category bulk pull is the primary firehose, but its trial quota throttles (503s). When
it stalls, this keeps the index growing through the other two aggregators. They're keyword-only
(no taxonomy like Adzuna), so we sweep a broad list of profession KEYWORDS across sectors to
approximate "all professions".

- Careerjet = the workhorse: generous, one call per (term × locale) over all 8 markets incl. BG.
- Jooble = used sparingly: its free tier is **500 requests TOTAL**, so it's capped hard per run.

Each sweep records a per-(source, term) tally in AggregatorPull, so — like the Adzuna board —
there's a live picture of what each aggregator has collected per profession. Fetch + persist
only (dedup); enrichment/retire stay in run_ingest_maintenance, run separately.
"""
from __future__ import annotations

import html as _html
import time
from datetime import datetime

from sqlalchemy import select

from ...data.models import AggregatorPull
from ...data.sources import careerjet, jooble
from .search import persist_postings

# Broad profession keywords spanning sectors — the keyword-API stand-in for Adzuna's taxonomy.
PROFESSION_TERMS = [
    "software developer", "data analyst", "devops engineer", "qa engineer", "product manager",
    "project manager", "accountant", "financial analyst", "auditor", "sales representative",
    "account manager", "marketing manager", "customer service", "human resources", "recruiter",
    "administrator", "office manager", "nurse", "doctor", "pharmacist", "care worker", "teacher",
    "mechanical engineer", "electrical engineer", "civil engineer", "electrician", "plumber",
    "welder", "driver", "warehouse operative", "logistics coordinator", "chef", "waiter",
    "retail assistant", "cleaner", "security officer", "lawyer", "graphic designer", "architect",
    "research scientist", "social worker", "construction worker",
]


def _record(db, source: str, term: str, fetched: int, added: int) -> None:
    row = db.execute(select(AggregatorPull).where(
        AggregatorPull.source == source, AggregatorPull.term == term)).scalar_one_or_none()
    if row is None:
        row = AggregatorPull(source=source, term=term, pulled=0, seen=0, runs=0)
        db.add(row)
    row.pulled += added
    row.seen += fetched
    row.runs += 1
    row.updated_at = datetime.utcnow()


def run_aggregator_fallback(session_factory, *, terms: list[str] | None = None,
                            careerjet_terms: int = 15, jooble_terms: int = 6,
                            sleep=time.sleep) -> dict:
    """Sweep Careerjet (primary) + Jooble (capped) over profession keywords and persist.

    ``careerjet_terms`` / ``jooble_terms`` bound how many keywords each source queries this run —
    Jooble stays small to protect its 500-request lifetime cap. Records per-term tallies for the
    boards. Returns per-source added counts.
    """
    terms = terms or PROFESSION_TERMS
    cj_added = jb_added = cj_terms = jb_terms = 0

    for term in terms[:max(0, careerjet_terms)]:                 # Careerjet — term × all locales
        posts = careerjet.fetch(search_terms=[term], sleep=sleep)
        cj_terms += 1
        with session_factory() as db:
            res = persist_postings(db, posts)
            _record(db, "careerjet", term, res["fetched"], res["added"])
            db.commit()
        cj_added += res["added"]

    for term in terms[:max(0, jooble_terms)]:                    # Jooble — sparing (500 cap)
        posts = jooble.fetch(search_terms=[term], sleep=sleep)
        jb_terms += 1
        with session_factory() as db:
            res = persist_postings(db, posts)
            _record(db, "jooble", term, res["fetched"], res["added"])
            db.commit()
        jb_added += res["added"]

    return {"careerjet_added": cj_added, "jooble_added": jb_added,
            "careerjet_terms": cj_terms, "jooble_terms": jb_terms,
            "total_added": cj_added + jb_added}


# ---- board -------------------------------------------------------------------

def status(db, source: str) -> dict:
    """Snapshot for a source's board: totals + per-term tallies."""
    rows = db.execute(select(AggregatorPull).where(AggregatorPull.source == source)
                      .order_by(AggregatorPull.pulled.desc())).scalars().all()
    pulled = sum(r.pulled for r in rows)
    seen = sum(r.seen for r in rows)
    last = max((r.updated_at for r in rows), default=None)
    return {
        "source": source, "terms": len(rows), "pulled": pulled, "seen": seen,
        "last_run": last.isoformat() if last else None,
        "rows": [{"term": r.term, "pulled": r.pulled, "seen": r.seen, "runs": r.runs,
                  "updated_at": r.updated_at.isoformat() if r.updated_at else None}
                 for r in rows],
    }


_ACCENTS = {                                    # (light accent, dark accent, icon)
    "jooble": ("#2563eb", "#5b9dff", "🟦"),
    "careerjet": ("#d9770c", "#f0a94b", "🟧"),
}
_META = {
    "jooble": ("Jooble", "пан-EU агрегатор · вкл. BG + Балтика"),
    "careerjet": ("Careerjet", "глобален агрегатор · 90+ държави вкл. BG"),
}


def render_board(source: str, st: dict, *, generated_at: datetime | None = None) -> str:
    """Self-contained per-profession collection board for one keyword aggregator."""
    gen = (generated_at or datetime.utcnow()).strftime("%Y-%m-%d %H:%M UTC")
    light, dark, _icon = _ACCENTS.get(source, ("#0e7c7b", "#2dd4bf", "▦"))
    name, tagline = _META.get(source, (source.title(), "keyword агрегатор"))
    rows = st["rows"]
    top = max((r["pulled"] for r in rows), default=1) or 1
    body = []
    for r in rows:
        pct = round(100 * r["pulled"] / top, 1)
        body.append(
            f'<tr><td>{_html.escape(r["term"])}</td>'
            f'<td class="num">{r["pulled"]:,}</td>'
            f'<td class="num muted">{r["seen"]:,}</td>'
            f'<td class="pg"><div class="bar"><span style="width:{pct:.1f}%"></span></div></td>'
            f'<td class="num muted">{r["runs"]}</td></tr>')
    return _BOARD_TMPL.format(
        name=name, tagline=tagline, gen=gen, light=light, dark=dark,
        pulled=f"{st['pulled']:,}", seen=f"{st['seen']:,}", terms=st["terms"],
        rows="\n".join(body) or '<tr><td colspan="5" class="muted">няма събрани обяви още</td></tr>')


_BOARD_TMPL = """<title>{name} — collection by profession</title>
<style>
  :root {{ --bg:#f6f7f9; --panel:#fff; --ink:#111823; --muted:#5b6675; --line:#e5e8ee;
    --accent:{light}; --track:#e4ebee; }}
  @media (prefers-color-scheme:dark) {{ :root {{ --bg:#0d1117; --panel:#161b22; --ink:#e8edf3;
    --muted:#8b96a5; --line:#232a34; --accent:{dark}; --track:#1d2c31; }} }}
  :root[data-theme="dark"] {{ --bg:#0d1117; --panel:#161b22; --ink:#e8edf3; --muted:#8b96a5;
    --line:#232a34; --accent:{dark}; --track:#1d2c31; }}
  :root[data-theme="light"] {{ --bg:#f6f7f9; --panel:#fff; --ink:#111823; --muted:#5b6675;
    --line:#e5e8ee; --accent:{light}; --track:#e4ebee; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }}
  .wrap {{ max-width:900px; margin:0 auto; padding:32px 24px 64px; }}
  .top {{ display:flex; align-items:baseline; justify-content:space-between; gap:16px;
    flex-wrap:wrap; }}
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
  td.pg {{ width:200px; }}
  .bar {{ height:8px; background:var(--track); border-radius:5px; overflow:hidden; }}
  .bar span {{ display:block; height:100%; background:var(--accent); border-radius:5px; }}
</style>
<div class="wrap">
  <div class="top">
    <h1>{name} <span>· {tagline}</span></h1>
    <div class="sub">updated {gen}</div>
  </div>
  <div class="hero">
    <div class="big">{pulled}<small>УНИКАЛНИ ОБЯВИ СЪБРАНИ</small></div>
    <div class="big">{seen}<small>ИЗТЕГЛЕНИ (вкл. дубли)</small></div>
    <div class="big">{terms}<small>ПРОФЕСИИ ОБХОДЕНИ</small></div>
  </div>
  <div class="tablewrap">
    <table>
      <thead><tr><th>Професия</th><th>Уникални</th><th>Изтеглени</th><th>Прогрес</th><th>Пускания</th></tr></thead>
      <tbody>
        {rows}
      </tbody>
    </table>
  </div>
</div>
"""
