"""SEO helpers: per-page meta/OG/canonical/robots tags and site-level JSON-LD.

Private pages (anything behind login) must be **noindex** — they hold personal data. Only
public marketing pages are indexable. The `page()` shell defaults to noindex; public pages
opt in explicitly. JobPosting structured data is intentionally deferred until we have public,
indexable job pages (Phase 2/4) — see ROADMAP.
"""
import json
from html import escape

from .config import settings

SITE_NAME = "Job Agent"


def abs_url(path: str = "/") -> str:
    base = settings.site_url.rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return base + path


def meta_tags(title: str, description: str, path: str = "/", *,
              noindex: bool = True, og_image: str | None = None) -> str:
    """Return the <head> meta block: description, canonical, robots, Open Graph, Twitter card."""
    canonical = abs_url(path)
    robots = "noindex, nofollow" if noindex else "index, follow"
    tags = [
        f'<meta name="description" content="{escape(description)}">',
        f'<meta name="robots" content="{robots}">',
        f'<link rel="canonical" href="{escape(canonical)}">',
        '<meta property="og:type" content="website">',
        f'<meta property="og:site_name" content="{escape(SITE_NAME)}">',
        f'<meta property="og:title" content="{escape(title)}">',
        f'<meta property="og:description" content="{escape(description)}">',
        f'<meta property="og:url" content="{escape(canonical)}">',
        '<meta name="twitter:card" content="summary">',
        f'<meta name="twitter:title" content="{escape(title)}">',
        f'<meta name="twitter:description" content="{escape(description)}">',
    ]
    if og_image:
        img = abs_url(og_image)
        tags.append(f'<meta property="og:image" content="{escape(img)}">')
        tags.append(f'<meta name="twitter:image" content="{escape(img)}">')
    return "\n".join(tags)


def _jsonld(obj: dict) -> str:
    return f'<script type="application/ld+json">{json.dumps(obj, ensure_ascii=False)}</script>'


def site_jsonld() -> str:
    """Organization + WebSite JSON-LD for the public site. Put on public pages only."""
    org = {"@context": "https://schema.org", "@type": "Organization",
           "name": SITE_NAME, "url": abs_url("/")}
    website = {"@context": "https://schema.org", "@type": "WebSite",
               "name": SITE_NAME, "url": abs_url("/")}
    return _jsonld(org) + _jsonld(website)
