"""Pure text utilities. HTML→text conversion used on job descriptions from any source, so the
requirement extractor (which expects text/line structure) can parse them."""
import html as _html
import re

_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_END_RE = re.compile(r"(?i)<\s*(br|/p|/div|/li|/h[1-6]|/tr)\s*/?>")
_WS_RE = re.compile(r"[ \t]+")


def html_to_text(s: str) -> str:
    """Convert an HTML (often entity-encoded) job description into readable plain text."""
    if not s:
        return ""
    s = _html.unescape(s)                 # &lt;p&gt; -> <p>
    s = _BLOCK_END_RE.sub("\n", s)        # block boundaries -> line breaks
    s = _TAG_RE.sub("", s)                # drop remaining tags
    s = _html.unescape(s)                 # leftover entities (&amp; -> &)
    lines = [_WS_RE.sub(" ", ln).strip() for ln in s.splitlines()]
    return "\n".join(ln for ln in lines if ln)
