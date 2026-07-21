"""Starter list of Greenhouse boards to crawl on demand ("Search now").

A temporary curated seed of verified, public Greenhouse boards (remote-friendly tech employers).
Step 16 (orchestrator) replaces this with a DB-managed, user-extendable company registry —
until then this gives the on-demand search something real to crawl. Format: (board_token, name).
"""
GREENHOUSE_BOARDS = [
    ("gitlab", "GitLab"),
    ("elastic", "Elastic"),
    ("remotecom", "Remote"),
    ("monzo", "Monzo"),
    ("vercel", "Vercel"),
]
