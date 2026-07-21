"""Adapter framework: a normalized posting shape + a registry of source adapters.

Each source (ATS API, RSS, logged-in browser) has an adapter that returns a list of RawPosting.
Everything downstream (dedup, requirement extraction, scoring) works off RawPosting, so adding a
new source is just a new adapter module — the pipeline doesn't change. See ROADMAP Phase 2.
"""
from __future__ import annotations

import hashlib
import html as _html
import re
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Posting


@dataclass
class RawPosting:
    """A job posting normalized across sources. `raw` keeps the untouched source payload."""
    source_kind: str                 # "ats_api" / "rss" / "browser"
    external_id: str                 # id at the source, for stable identity
    title: str
    company: str
    location: str = ""
    url: str = ""                    # canonical posting URL
    apply_url: str = ""              # direct apply URL (for ATS, usually == url)
    description: str = ""            # plain-text job description
    posted_at: datetime | None = None
    raw: dict = field(default_factory=dict)

    def content_hash(self) -> str:
        """Stable identity for dedup. Prefer the canonical apply/URL; else source+id+company."""
        key = (self.apply_url or self.url
               or f"{self.source_kind}:{self.external_id}:{self.company}:{self.title}")
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:64]


# ---------- HTML → text (ATS descriptions arrive as entity-encoded HTML) ----------
_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_END_RE = re.compile(r"(?i)<\s*(br|/p|/div|/li|/h[1-6]|/tr)\s*/?>")
_WS_RE = re.compile(r"[ \t]+")


def html_to_text(s: str) -> str:
    """Convert an HTML (often entity-encoded) job description into readable plain text, so the
    requirement extractor (which expects text/line structure) can parse it."""
    if not s:
        return ""
    s = _html.unescape(s)                 # &lt;p&gt; -> <p>
    s = _BLOCK_END_RE.sub("\n", s)        # block boundaries -> line breaks
    s = _TAG_RE.sub("", s)                # drop remaining tags
    s = _html.unescape(s)                 # leftover entities (&amp; -> &)
    lines = [_WS_RE.sub(" ", ln).strip() for ln in s.splitlines()]
    return "\n".join(ln for ln in lines if ln)


# ---------- adapter registry ----------
_REGISTRY: dict[str, object] = {}


def register(name: str, adapter) -> None:
    _REGISTRY[name] = adapter


def get_adapter(name: str):
    return _REGISTRY.get(name)


# ---------- persistence (first-cut dedup by content_hash; semantic dedup is Step 12) ----------
def ingest(db: Session, postings: list[RawPosting], source_id: int | None = None) -> dict:
    """Upsert RawPostings into the Posting table, keyed by content_hash — already-seen postings
    are skipped. Requirement extraction runs later (Step 13). Returns {added, skipped}."""
    added = skipped = 0
    for rp in postings:
        chash = rp.content_hash()
        if db.execute(select(Posting.id).where(Posting.content_hash == chash)).first():
            skipped += 1
            continue
        db.add(Posting(
            title=rp.title, company=rp.company, url=rp.url, apply_url=rp.apply_url,
            location=rp.location, description=rp.description, requirements=None,
            content_hash=chash, source_id=source_id,
        ))
        added += 1
    if added:
        db.commit()
    return {"added": added, "skipped": skipped}
