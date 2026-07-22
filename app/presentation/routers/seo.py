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

# Public, indexable URLs: both landing languages + the profession pages (EN + BG variants).
PUBLIC_PATHS = (["/", "/bg", "/jobs", "/bg/jobs"]
                + [f"/jobs/{o['id']}" for o in OCCUPATIONS]
                + [f"/bg/jobs/{o['id']}" for o in OCCUPATIONS])


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
