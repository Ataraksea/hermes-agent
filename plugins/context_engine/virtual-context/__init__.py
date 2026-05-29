"""Virtual Context Plugin — context engine backed by virtual-context.

Drop-in alternative to hermes-lcm that uses the virtual-context library
for segment-based compaction, retrieval-augmented assembly, and tag-driven
context management.
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
            "is the virtual-context package installed?",
            exc,
        )
        return

    # Resolve hermes_home for storage scoping
    hermes_home = ""
    try:
        from hermes_cli.config import get_hermes_home
        hermes_home = str(get_hermes_home())
    except Exception:
        hermes_home = os.environ.get(
            "HERMES_HOME", os.path.expanduser("~/.hermes")
        )

    engine = VirtualContextAdapter(hermes_home=hermes_home)
    ctx.register_context_engine(engine)
    logger.info("Virtual Context plugin loaded — virtual-context engine active")
