"""Virtual Context Plugin — context engine backed by virtual-context.

Drop-in alternative context plugin that uses the virtual-context library
for segment-based compaction, retrieval-augmented assembly, and tag-driven
context management. Activate with ``context.engine: virtual-context`` in
config.yaml.
"""

import logging
import os

logger = logging.getLogger(__name__)


def register(ctx):
    """Plugin entry point — register the Virtual Context engine."""
    try:
        from .engine import VirtualContextAdapter
    except ImportError as exc:
        logger.warning(
            "virtual-context plugin could not import engine: %s — "
            "is the virtual-context package installed? (pip install virtual-context)",
            exc,
        )
        return

    # Resolve the active HERMES_HOME for profile-safe storage scoping.
    try:
        from hermes_constants import get_hermes_home
        hermes_home = str(get_hermes_home())
    except Exception:
        hermes_home = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))

    engine = VirtualContextAdapter(hermes_home=hermes_home)
    ctx.register_context_engine(engine)
    logger.info("Virtual Context plugin loaded — virtual-context engine active")
