"""Source adapters — one dedicated, isolated module per source (CLAUDE.md §5).
Importing this package registers all built-in adapters."""
from .base import register, get_adapter  # noqa: F401
from . import greenhouse  # noqa: F401  (registers "greenhouse")
from . import dev_bg      # noqa: F401  (registers "dev_bg")
from . import jobtiger    # noqa: F401  (registers "jobtiger")
from . import remoteok    # noqa: F401  (registers "remoteok")
from . import wwr         # noqa: F401  (registers "wwr")
from . import lever       # noqa: F401  (registers "lever")
from . import ashby       # noqa: F401  (registers "ashby")
