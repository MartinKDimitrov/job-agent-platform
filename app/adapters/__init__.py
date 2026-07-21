"""Source adapters. Importing this package registers all built-in adapters.

One dedicated module per source (see CLAUDE.md §5 isolation rule): greenhouse (ATS API),
dev_bg (RSS), jobtiger (sitemap+HTML). Adding a source = adding a module here.
"""
from .base import RawPosting, html_to_text, ingest, register, get_adapter  # noqa: F401
from . import greenhouse  # noqa: F401  (registers "greenhouse")
from . import dev_bg      # noqa: F401  (registers "dev_bg")
from . import jobtiger    # noqa: F401  (registers "jobtiger")
from . import remoteok    # noqa: F401  (registers "remoteok")
from . import wwr         # noqa: F401  (registers "wwr")
from . import lever       # noqa: F401  (registers "lever")
from . import ashby       # noqa: F401  (registers "ashby")
