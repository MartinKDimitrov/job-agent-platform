"""Public SEO endpoints: robots.txt and sitemap.xml.

Private, per-user areas are disallowed from crawling and never listed in the sitemap. As public
pages are added (Phase 4 city/profession landing pages) they go in PUBLIC_PATHS.
"""
from fastapi import APIRouter
from fastapi.responses import PlainTextResponse, Response

from ...core.config import settings

router = APIRouter()

# Areas behind login / holding personal data — keep crawlers out.
PRIVATE_PREFIXES = ["/profiles", "/account", "/sources", "/documents", "/onboarding",
                    "/login", "/register", "/auth"]
from ...domain.taxonomy import OCCUPATIONS
from ..i18n import LANGS

# Public, indexable URLs: every landing language + the profession pages in all languages
# (English lives at the unprefixed path, other languages under /{lang}/...).
def _lang_prefixed(tail: str) -> list[str]:
    return [tail] + [f"/{code}{tail}" for code in LANGS if code != "en"]


PUBLIC_PATHS = (["/"] + [f"/{code}" for code in LANGS if code != "en"]
                + _lang_prefixed("/jobs")
                + [p for o in OCCUPATIONS for p in _lang_prefixed(f"/jobs/{o['id']}")])


@router.get("/robots.txt", response_class=PlainTextResponse)
def robots_txt():
    base = settings.site_url.rstrip("/")
    lines = ["User-agent: *"]
    lines += [f"Disallow: {p}" for p in PRIVATE_PREFIXES]
    lines.append(f"Sitemap: {base}/sitemap.xml")
    return "\n".join(lines) + "\n"


@router.get("/sitemap.xml")
def sitemap_xml():
    base = settings.site_url.rstrip("/")
    urls = "".join(f"<url><loc>{base}{p}</loc></url>" for p in PUBLIC_PATHS)
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
           f'{urls}</urlset>')
    return Response(content=xml, media_type="application/xml")
