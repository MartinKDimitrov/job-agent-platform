"""Adzuna bulk pull — draining ALL professions, in resumable batches.

We serve any profession, not just the test profiles, so we can't drive Adzuna by role terms:
we drain it by its own taxonomy. Adzuna partitions every posting into ~30 CATEGORIES; the plan
is CATEGORY × COUNTRY = one slice per (country, category), each an independent, resumable cursor
(``AdzunaPull``). A run walks slices, fetching one search page at a time, persisting, then
committing the advanced cursor after EVERY page — so progress is durable to the ~50-posting page,
checkable at any moment, and a killed run resumes exactly where it stopped.

The real constraint is the trial CALL quota, so a run takes a ``call_budget`` and spreads it:
slices are visited least-pulled-first and capped at ``pages_per_slice`` per run, so the budget
fans out across professions/countries instead of sinking into one huge category (IT alone is
~28k in DE). Nightly cron just calls ``run_bulk`` again; the cursors carry the state.
"""
from __future__ import annotations

import html as _html
import time
from datetime import datetime

from sqlalchemy import select

from ...data.models import AdzunaPull
from ...data.sources import adzuna
from .search import persist_postings

COUNTRIES = adzuna.COUNTRIES                 # de/fr/it/gb/es/nl/pl
RESULTS_PER_PAGE = adzuna.RESULTS_PER_PAGE   # 50
DEFAULT_CALL_BUDGET = 200                    # Adzuna calls per run — spread across slices
DEFAULT_PAGES_PER_SLICE = 20                 # cap per slice per run -> budget fans out


def ensure_slices(session_factory, countries=COUNTRIES) -> int:
    """Seed one AdzunaPull row per (country, category) from Adzuna's live taxonomy. Idempotent:
    existing slices are left untouched (labels refreshed). Returns the slice count."""
    created = 0
    for country in countries:
        cats = adzuna.categories(country)
        if not cats:
            continue                          # keys unset or API down -> skip, retry next run
        with session_factory() as db:
            existing = {c for (c,) in db.execute(
                select(AdzunaPull.category).where(AdzunaPull.country == country)).all()}
            for tag, label in cats:
                if not tag:
                    continue
                if tag in existing:
                    row = db.execute(select(AdzunaPull).where(
                        AdzunaPull.country == country, AdzunaPull.category == tag)).scalar_one()
                    row.label = label or row.label
                else:
                    db.add(AdzunaPull(country=country, category=tag, label=label or ""))
                    created += 1
            db.commit()
    return created


def run_bulk(session_factory, *, call_budget: int = DEFAULT_CALL_BUDGET,
             pages_per_slice: int = DEFAULT_PAGES_PER_SLICE,
             results_per_page: int = RESULTS_PER_PAGE, countries=COUNTRIES,
             fail_backoff_base: float = 5.0, fail_backoff_max: float = 120.0,
             sleep=time.sleep) -> dict:
    """Drain up to ``call_budget`` pages across not-yet-done slices, least-pulled-first, at most
    ``pages_per_slice`` per slice this run. Commits after every page (durable cursor). Returns a
    run summary; progress persists in AdzunaPull for the board/status.

    503-aware pacing: a failed call (503 / read timeout = Adzuna rate-limiting us) triggers an
    exponential backoff — ``base * 2**(consecutive_failures-1)`` capped at ``fail_backoff_max``
    — so a struggling API gets breathing room instead of being hammered; a success resets it."""
    if not adzuna._configured():
        return {"configured": False, "calls": 0, "added": 0, "slices_touched": 0, "failed": 0}

    ensure_slices(session_factory, countries)

    with session_factory() as db:
        # least-pulled first so the budget fans out; ties break by (category, country) so a run
        # spreads one profession across ALL markets before deepening — the board fills broadly,
        # not one-country-at-a-time.
        pending = db.execute(
            select(AdzunaPull.id).where(AdzunaPull.done.is_(False),
                                        AdzunaPull.country.in_(countries))
            .order_by(AdzunaPull.pulled.asc(), AdzunaPull.category.asc(),
                      AdzunaPull.country.asc())).scalars().all()

    calls = added = touched = failed = 0
    consec_fail = 0
    for slice_id in pending:
        if calls >= call_budget:
            break
        pages_this_slice = 0
        touched_this = False
        while calls < call_budget and pages_this_slice < pages_per_slice:
            with session_factory() as db:
                row = db.get(AdzunaPull, slice_id)
                if row is None or row.done:
                    break
                country, category, page = row.country, row.category, row.next_page
            posts, total = adzuna.fetch_page(country, page, category=category,
                                             results_per_page=results_per_page)
            calls += 1
            pages_this_slice += 1
            if posts is None:
                # the call failed (e.g. transient 503 / read timeout = we're being rate-limited)
                # — leave the cursor exactly where it is (retry this same page next run) and NEVER
                # mark the slice done. Back off exponentially so we stop hammering the API.
                failed += 1
                consec_fail += 1
                sleep(min(fail_backoff_base * 2 ** (consec_fail - 1), fail_backoff_max))
                break
            consec_fail = 0                       # a good page — clear the backoff
            with session_factory() as db:
                row = db.get(AdzunaPull, slice_id)
                res = persist_postings(db, posts)
                row.pulled += res["added"]
                row.total = total or row.total
                row.next_page = page + 1
                # A short page (or empty) means we've drained this slice's window.
                if len(posts) < results_per_page:
                    row.done = True
                row.updated_at = datetime.utcnow()
                db.commit()
                added += res["added"]
                done = row.done
            touched_this = True
            if done:
                break
            sleep(adzuna.CALL_DELAY)
        if touched_this:
            touched += 1
    return {"configured": True, "calls": calls, "added": added, "slices_touched": touched,
            "failed": failed}


def status(db) -> dict:
    """Snapshot for the board / CLI: overall %, per-country and per-slice progress."""
    rows = db.execute(select(AdzunaPull).order_by(
        AdzunaPull.country.asc(), AdzunaPull.pulled.desc())).scalars().all()
    pulled = sum(r.pulled for r in rows)
    est_total = sum(r.total for r in rows)
    done = sum(1 for r in rows if r.done)
    by_country: dict[str, dict] = {}
    for r in rows:
        c = by_country.setdefault(r.country.upper(),
                                  {"pulled": 0, "total": 0, "slices": 0, "done": 0})
        c["pulled"] += r.pulled
        c["total"] += r.total
        c["slices"] += 1
        c["done"] += 1 if r.done else 0
    return {
        "slices": len(rows),
        "slices_done": done,
        "pulled": pulled,
        "est_total": est_total,
        "pct": round(100 * pulled / est_total, 1) if est_total else 0.0,
        "by_country": by_country,
        "slices_detail": [
            {"country": r.country.upper(), "category": r.category, "label": r.label,
             "pulled": r.pulled, "total": r.total, "next_page": r.next_page, "done": r.done,
             "updated_at": r.updated_at.isoformat() if r.updated_at else None}
            for r in rows],
    }


def run_drain(session_factory, *, batch_budget: int = DEFAULT_CALL_BUDGET, max_calls: int = 5000,
              stall_runs: int = 3, batch_pause: float = 2.0, board_path: str | None = None,
              countries=COUNTRIES, log=print, sleep=time.sleep) -> dict:
    """Run batches back-to-back until every slice is drained OR the trial quota throttles us.

    Adzuna serves full pages arbitrarily deep, so a slice only drains after its whole count is
    paged — full drain is thousands of calls, quota-bounded. This loops run_bulk, stopping on:
    all slices done; ``max_calls`` safety cap; or ``stall_runs`` consecutive batches that add
    nothing (a 503/quota storm — back off rather than hammer the key). Rewrites the board file
    after each batch when ``board_path`` is set (publishing stays a manual step)."""
    total_calls = total_added = batches = 0
    stalled = 0
    while total_calls < max_calls:
        res = run_bulk(session_factory, call_budget=batch_budget, countries=countries, sleep=sleep)
        if not res.get("configured"):
            return {"configured": False, "batches": batches, "calls": 0, "added": 0}
        batches += 1
        total_calls += res["calls"]
        total_added += res["added"]
        with session_factory() as db:
            st = status(db)
            if board_path:
                try:
                    with open(board_path, "w", encoding="utf-8") as fh:
                        fh.write(render_board(st))
                except OSError:
                    pass
        log(f"batch {batches}: +{res['added']} postings, {res['calls']} calls "
            f"({res.get('failed', 0)} failed) | pulled={st['pulled']} "
            f"done={st['slices_done']}/{st['slices']}")
        if res["calls"] == 0 or st["slices_done"] >= st["slices"]:
            break                                     # nothing pending / everything drained
        stalled = stalled + 1 if res["added"] == 0 else 0
        if stalled >= stall_runs:
            log(f"stalled {stalled} batches (quota/503) — backing off")
            break
        sleep(batch_pause)
    with session_factory() as db:
        st = status(db)
    return {"configured": True, "batches": batches, "calls": total_calls, "added": total_added,
            "stalled": stalled >= stall_runs, "slices_done": st["slices_done"],
            "slices": st["slices"], "pulled": st["pulled"]}


def run_recency_refresh(session_factory, *, call_budget: int = 300, max_pages_per_slice: int = 3,
                        results_per_page: int = RESULTS_PER_PAGE, countries=COUNTRIES,
                        sleep=time.sleep) -> dict:
    """Cheap steady-state maintenance — catch only the NEW postings, not re-drain the catalogue.

    The bulk pull (run_bulk/run_drain) is for the one-time fill. Once a market is seeded, this
    is what runs nightly: for every country×category it pages Adzuna **sorted by date** (newest
    first) and stops the moment a page adds nothing new — i.e. we've reached jobs we already have
    (content_hash dedup makes re-seen postings a cheap SKIP). So a slice usually costs 1 page,
    a few when there's a burst. Independent of the drain cursor (works even on drained slices);
    enrichment/retirement stay in run_ingest_maintenance, run separately.
    """
    if not adzuna._configured():
        return {"configured": False, "calls": 0, "added": 0, "slices": 0}

    ensure_slices(session_factory, countries)
    with session_factory() as db:
        slices = db.execute(
            select(AdzunaPull.country, AdzunaPull.category)
            .where(AdzunaPull.country.in_(countries))
            .order_by(AdzunaPull.category.asc(), AdzunaPull.country.asc())).all()

    calls = added = failed = touched = 0
    for country, category in slices:
        if calls >= call_budget:
            break
        for page in range(1, max_pages_per_slice + 1):
            if calls >= call_budget:
                break
            posts, _total = adzuna.fetch_page(country, page, category=category,
                                              results_per_page=results_per_page, sort_by="date")
            calls += 1
            if posts is None:                     # failed call — skip this slice this run
                failed += 1
                break
            with session_factory() as db:
                res = persist_postings(db, posts)
                db.commit()
            added += res["added"]
            if res["added"]:
                touched += 1
            # newest-first: a page with no NEW jobs means we've met what we already have -> stop.
            # a short page means the slice ran out.
            if res["added"] == 0 or len(posts) < results_per_page:
                break
            sleep(adzuna.CALL_DELAY)
    return {"configured": True, "calls": calls, "added": added, "failed": failed,
            "slices": len(slices), "slices_with_new": touched}


_FLAG = {"DE": "🇩🇪", "FR": "🇫🇷", "IT": "🇮🇹", "GB": "🇬🇧", "ES": "🇪🇸", "NL": "🇳🇱", "PL": "🇵🇱"}


def _bar(pct: float, tone: str = "accent") -> str:
    pct = max(0.0, min(100.0, pct))
    return (f'<div class="bar"><span class="fill {tone}" style="width:{pct:.1f}%"></span></div>')


def render_board(st: dict, *, generated_at: datetime | None = None) -> str:
    """Self-contained progress board (theme-aware, no external assets) rendered from status().
    Regenerated on demand and by the nightly pull, so the fields advance as the cursors do."""
    gen = (generated_at or datetime.utcnow()).strftime("%Y-%m-%d %H:%M UTC")
    pulled, est, pct = st["pulled"], st["est_total"], st["pct"]
    countries = sorted(st["by_country"].items())

    cards = []
    for iso, c in countries:
        cpct = round(100 * c["pulled"] / c["total"], 1) if c["total"] else 0.0
        cards.append(
            f'<div class="cc"><div class="cc-h">{_FLAG.get(iso, "")} <b>{iso}</b>'
            f'<span class="muted">{c["done"]}/{c["slices"]} slices</span></div>'
            f'<div class="cc-n">{c["pulled"]:,}<span class="muted"> / {c["total"]:,}</span></div>'
            f'{_bar(cpct)}</div>')

    rows = []
    for s in st["slices_detail"]:
        spct = round(100 * s["pulled"] / s["total"], 1) if s["total"] else 0.0
        tone = "done" if s["done"] else ("accent" if s["pulled"] else "idle")
        badge = "done" if s["done"] else ("live" if s["pulled"] else "queued")
        rows.append(
            f'<tr><td>{_FLAG.get(s["country"], "")} {s["country"]}</td>'
            f'<td>{_html.escape(s["label"] or s["category"])}</td>'
            f'<td class="num">{s["pulled"]:,}</td>'
            f'<td class="num muted">{s["total"]:,}</td>'
            f'<td class="pgcell">{_bar(spct, tone)}</td>'
            f'<td><span class="pill {badge}">{badge}</span></td></tr>')

    return _BOARD_TMPL.format(
        gen=gen, pulled=f"{pulled:,}", est=f"{est:,}", pct=f"{pct:.1f}",
        pct_bar=_bar(pct), slices=st["slices"], slices_done=st["slices_done"],
        cards="\n".join(cards), rows="\n".join(rows))


_BOARD_TMPL = """<title>Adzuna Bulk Pull — All Professions</title>
<style>
  :root {{
    --bg:#f6f7f9; --panel:#ffffff; --ink:#111823; --muted:#5b6675; --line:#e5e8ee;
    --accent:#0e7c7b; --accent-soft:#d3ecec; --done:#1f9d55; --done-soft:#d6f0e0;
    --idle:#c3c9d3; --amber:#b7791f;
  }}
  @media (prefers-color-scheme:dark) {{
    :root {{
      --bg:#0d1117; --panel:#161b22; --ink:#e8edf3; --muted:#8b96a5; --line:#232a34;
      --accent:#2dd4bf; --accent-soft:#123b3a; --done:#3fb950; --done-soft:#123a22;
      --idle:#30363d; --amber:#d29922;
    }}
  }}
  :root[data-theme="light"] {{
    --bg:#f6f7f9; --panel:#ffffff; --ink:#111823; --muted:#5b6675; --line:#e5e8ee;
    --accent:#0e7c7b; --accent-soft:#d3ecec; --done:#1f9d55; --done-soft:#d6f0e0;
    --idle:#c3c9d3; --amber:#b7791f;
  }}
  :root[data-theme="dark"] {{
    --bg:#0d1117; --panel:#161b22; --ink:#e8edf3; --muted:#8b96a5; --line:#232a34;
    --accent:#2dd4bf; --accent-soft:#123b3a; --done:#3fb950; --done-soft:#123a22;
    --idle:#30363d; --amber:#d29922;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    -webkit-font-smoothing:antialiased; }}
  .wrap {{ max-width:1100px; margin:0 auto; padding:32px 24px 64px; }}
  .top {{ display:flex; align-items:baseline; justify-content:space-between; gap:16px;
    flex-wrap:wrap; margin-bottom:4px; }}
  h1 {{ font-size:22px; margin:0; letter-spacing:-.01em; }}
  .sub {{ color:var(--muted); font-size:13px; }}
  .hero {{ background:var(--panel); border:1px solid var(--line); border-radius:14px;
    padding:24px; margin:20px 0 24px; }}
  .big {{ font-size:44px; font-weight:700; letter-spacing:-.02em;
    font-variant-numeric:tabular-nums; }}
  .big span {{ font-size:22px; color:var(--muted); font-weight:500; }}
  .herometa {{ display:flex; gap:28px; flex-wrap:wrap; margin-top:14px; color:var(--muted);
    font-size:13px; }}
  .herometa b {{ color:var(--ink); font-variant-numeric:tabular-nums; }}
  .bar {{ position:relative; height:8px; background:var(--idle); border-radius:6px;
    overflow:hidden; margin-top:10px; }}
  .fill {{ position:absolute; inset:0 auto 0 0; border-radius:6px; }}
  .fill.accent {{ background:var(--accent); }}
  .fill.done {{ background:var(--done); }}
  .fill.idle {{ background:transparent; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(190px,1fr)); gap:12px;
    margin-bottom:28px; }}
  .cc {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:14px; }}
  .cc-h {{ display:flex; align-items:center; gap:6px; font-size:13px; }}
  .cc-h .muted {{ margin-left:auto; }}
  .cc-n {{ font-size:22px; font-weight:700; margin-top:6px; font-variant-numeric:tabular-nums; }}
  .muted {{ color:var(--muted); font-weight:400; font-size:13px; }}
  h2 {{ font-size:14px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted);
    margin:0 0 10px; }}
  .tablewrap {{ overflow-x:auto; background:var(--panel); border:1px solid var(--line);
    border-radius:12px; }}
  table {{ width:100%; border-collapse:collapse; font-size:13.5px; }}
  th,td {{ text-align:left; padding:9px 14px; border-bottom:1px solid var(--line);
    white-space:nowrap; }}
  th {{ font-size:11px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted);
    position:sticky; top:0; background:var(--panel); }}
  tr:last-child td {{ border-bottom:none; }}
  td.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  td.pgcell {{ width:180px; }}
  td.pgcell .bar {{ margin:0; }}
  .pill {{ font-size:11px; padding:2px 9px; border-radius:20px; font-weight:600;
    text-transform:uppercase; letter-spacing:.03em; }}
  .pill.done {{ background:var(--done-soft); color:var(--done); }}
  .pill.live {{ background:var(--accent-soft); color:var(--accent); }}
  .pill.queued {{ background:var(--idle); color:var(--muted); }}
</style>
<div class="wrap">
  <div class="top">
    <h1>Adzuna Bulk Pull <span class="sub">· all professions</span></h1>
    <div class="sub">updated {gen}</div>
  </div>
  <div class="hero">
    <div class="big">{pulled}<span> / {est} live postings</span></div>
    {pct_bar}
    <div class="herometa">
      <div><b>{pct}%</b> of visible catalogue pulled</div>
      <div><b>{slices_done}</b> / <b>{slices}</b> slices drained</div>
      <div>30 categories × 7 countries · resumable cursor</div>
    </div>
  </div>
  <div class="grid">
    {cards}
  </div>
  <h2>Per slice — category × country</h2>
  <div class="tablewrap">
    <table>
      <thead><tr><th>Country</th><th>Category</th><th>Pulled</th><th>Catalogue</th>
        <th>Progress</th><th>State</th></tr></thead>
      <tbody>
        {rows}
      </tbody>
    </table>
  </div>
</div>
"""

