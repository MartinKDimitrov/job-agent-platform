"""Domain entities — pure data shapes, no framework or I/O dependencies.

RawPosting is the normalized job posting every source adapter produces and every pipeline stage
(dedup → extraction → scoring) consumes. Keeping it here means the domain never depends on how
postings are fetched or stored.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RawPosting:
    """A job posting normalized across sources. `raw` keeps the untouched source payload."""
    source_kind: str                 # "ats_api" / "rss" / "browser" / "html"
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
