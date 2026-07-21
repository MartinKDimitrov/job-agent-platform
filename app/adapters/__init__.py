"""Source adapters. Importing this package registers all built-in adapters."""
from .base import RawPosting, html_to_text, ingest, register, get_adapter  # noqa: F401
from . import greenhouse  # noqa: F401  (registers "greenhouse" on import)
