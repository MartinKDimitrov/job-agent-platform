"""Print/PDF template for generated documents (CV / cover letter).

The design was produced by Lovable (project 038dd6c8, public/document-template.html) per the
product decision to entrust document design to it: A4 print-optimized, one accent color
matching the app (#1f3864), system fonts (Cyrillic-safe), ATS-friendly, screen preview as a
centered sheet with a Download PDF button (window.print) hidden in print. The same HTML will
be rendered server-side to a real .pdf at deploy time (weasyprint) — the template carries over.
"""
from html import escape

_TEMPLATE = """<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="robots" content="noindex, nofollow" />
<title>{title} — {name}</title>
<style>
  :root {{
    --accent: #1f3864; --ink: #1a1a1a; --muted: #5b6472; --rule: #d4d8df;
    --sheet: #ffffff; --bg: #eceef2;
    --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Helvetica, Arial, sans-serif;
    --serif: Georgia, "Times New Roman", Times, serif;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; background: var(--bg); color: var(--ink);
    font-family: var(--serif); font-size: 11pt; line-height: 1.5; -webkit-font-smoothing: antialiased; }}
  .sheet {{ background: var(--sheet); width: 210mm; min-height: 297mm; margin: 24px auto;
    padding: 18mm; box-shadow: 0 4px 24px rgba(20,30,50,.12), 0 1px 3px rgba(20,30,50,.08); }}
  .doc-header {{ margin-bottom: 10mm; }}
  .doc-title {{ font-family: var(--sans); font-size: 9pt; font-weight: 600; letter-spacing: .28em;
    text-transform: uppercase; color: var(--accent); margin: 0 0 6mm 0; }}
  .doc-name {{ font-family: var(--sans); font-size: 26pt; font-weight: 300; letter-spacing: -.01em;
    color: var(--ink); margin: 0; line-height: 1.1; }}
  .doc-role {{ font-family: var(--sans); font-size: 11pt; font-weight: 400; color: var(--muted);
    margin: 3mm 0 0 0; letter-spacing: .01em; }}
  .doc-rule {{ border: 0; border-top: 1px solid var(--accent); height: 0; margin: 7mm 0 8mm 0; width: 100%; }}
  .doc-content {{ font-family: var(--serif); font-size: 11pt; line-height: 1.6; color: var(--ink);
    white-space: pre-wrap; word-wrap: break-word; overflow-wrap: break-word; max-width: 62em; hyphens: auto; }}
  .doc-footer {{ margin-top: 12mm; padding-top: 4mm; border-top: 1px solid var(--rule);
    font-family: var(--sans); font-size: 8.5pt; color: var(--muted); letter-spacing: .02em; }}
  .print-btn {{ position: fixed; top: 16px; right: 16px; z-index: 1000; font-family: var(--sans);
    font-size: 13px; font-weight: 600; letter-spacing: .02em; color: #fff; background: var(--accent);
    border: 0; padding: 10px 18px; border-radius: 6px; cursor: pointer;
    box-shadow: 0 2px 8px rgba(31,56,100,.25); }}
  .print-btn:hover {{ background: #16294a; }}
  @page {{ size: A4; margin: 18mm; }}
  @media print {{
    html, body {{ background: #fff; }}
    .sheet {{ width: auto; min-height: 0; margin: 0; padding: 0; box-shadow: none; }}
    .print-btn {{ display: none !important; }}
    .doc-content {{ orphans: 3; widows: 3; }}
    h1, h2, h3, .doc-header {{ page-break-after: avoid; break-after: avoid; }}
    .doc-footer {{ page-break-before: avoid; }}
  }}
</style>
</head>
<body>
  <button class="print-btn" onclick="window.print()" aria-label="Download PDF">Download PDF</button>
  <main class="sheet" role="document">
    <header class="doc-header">
      <p class="doc-title">{title}</p>
      <h1 class="doc-name">{name}</h1>
      <p class="doc-role">{role}</p>
      <hr class="doc-rule" />
    </header>
    <div class="doc-content">{content}</div>
    <footer class="doc-footer">{footer}</footer>
  </main>
</body>
</html>"""


def render_document_html(*, title: str, name: str, role: str, content: str,
                         footer: str, lang: str = "en") -> str:
    """Fill the Lovable-designed template with escaped values."""
    return _TEMPLATE.format(
        lang=escape(lang), title=escape(title), name=escape(name),
        role=escape(role), content=escape(content), footer=escape(footer))
