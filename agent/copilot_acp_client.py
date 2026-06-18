"""Backwards-compatible alias for the Copilot ACP client.

The generic ACP client now lives in ``agent.acp_client``.  This module
re-exports ``CopilotACPClient`` so existing imports continue to work.
"""

from __future__ import annotations

import re
from typing import Any

from agent.acp_client import ACPClient

# Re-export the marker so existing checks (``base_url.startswith(...)``) work.
ACP_MARKER_BASE_URL = "acp://copilot"

_TOOL_CALL_BLOCK_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
_TOOL_CALL_JSON_RE = re.compile(r"\{\s*\"id\"\s*:\s*\"[^\"]+\"\s*,\s*\"type\"\s*:\s*\"function\"\s*,\s*\"function\"\s*:\s*\{.*?\}\s*\}", re.DOTALL)

# Stderr fingerprint of the deprecated `gh copilot` CLI extension
# (https://github.blog/changelog/2025-09-25-upcoming-deprecation-of-gh-copilot-cli-extension).
# We require BOTH the literal product name ("gh-copilot") AND a deprecation
# marker, so generic stderr from the NEW `@github/copilot` CLI — whose repo
# is github.com/github/copilot-cli and which legitimately mentions "copilot-cli"
# in its own banners and error messages — doesn't get misclassified as the
# deprecated extension.
_DEPRECATION_REQUIRED = ("gh-copilot",)
_DEPRECATION_MARKERS = (
    "has been deprecated",
    "no commands will be executed",
)


def _is_gh_copilot_deprecation_message(stderr_text: str) -> bool:
    """True iff stderr looks like the deprecated gh-copilot extension's banner."""

    lower = stderr_text.lower()
    if not any(req in lower for req in _DEPRECATION_REQUIRED):
        return False
    return any(marker in lower for marker in _DEPRECATION_MARKERS)


class CopilotACPClient(ACPClient):
    """Copilot-specific ACP client — thin wrapper around the generic ACPClient."""

    def __init__(self, **kwargs: Any):
        kwargs.setdefault("agent_name", "copilot")
        super().__init__(**kwargs)
