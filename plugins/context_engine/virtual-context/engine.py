"""Virtual Context adapter — ContextEngine subclass wrapping VirtualContextEngine.

Translates between Hermes's ContextEngine contract (OpenAI-format message
lists, token tracking, compress/should_compress) and the virtual-context
library's segment/retrieval/compaction API.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.context_engine import ContextEngine

logger = logging.getLogger(__name__)


class VirtualContextAdapter(ContextEngine):
    """Thin adapter that delegates to ``VirtualContextEngine``."""

    # ── Identity ──────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "virtual-context"

    # ── Construction ──────────────────────────────────────────────────────

    def __init__(self, *, hermes_home: str = "") -> None:
        self._hermes_home = hermes_home or os.path.expanduser("~/.hermes")
        self._engine: Optional[Any] = None  # lazy — created on first session
        self._config_path: Optional[Path] = None
        self._session_id: Optional[str] = None

        # Token tracking (read by run_agent.py)
        self.last_prompt_tokens: int = 0
        self.last_completion_tokens: int = 0
        self.last_total_tokens: int = 0
        self.threshold_tokens: int = 0
        self.context_length: int = 0
        self.compression_count: int = 0

    # ── Lazy engine bootstrap ─────────────────────────────────────────────

    def _ensure_engine(self) -> Any:
        """Create the VirtualContextEngine on first use."""
        if self._engine is not None:
            return self._engine

        from virtual_context.config import load_config
        from virtual_context.engine import VirtualContextEngine

        # Look for config: explicit env var → hermes home → virtual-context repo
        config_path = os.environ.get("VIRTUAL_CONTEXT_CONFIG")
        if config_path:
            self._config_path = Path(config_path)
        else:
            candidates = [
                Path(self._hermes_home) / "virtual-context.yaml",
                Path(self._hermes_home) / "virtual-context" / "virtual-context.yaml",
                Path.home() / ".hermes" / "virtual-context" / "virtual-context.yaml",
            ]
            for c in candidates:
                if c.is_file():
                    self._config_path = c
                    break

        if self._config_path and self._config_path.is_file():
            config = load_config(config_path=self._config_path)
            logger.info("Virtual Context config loaded from %s", self._config_path)
        else:
            config = load_config()
            logger.info("Virtual Context using default/auto-discovered config")

        self._engine = VirtualContextEngine(config=config)
        self.context_length = config.context_window
        self.threshold_tokens = int(self.context_length * self.threshold_percent)
        return self._engine

    # ── ContextEngine required methods ────────────────────────────────────

    def update_from_response(self, usage: Dict[str, Any]) -> None:
        self.last_prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
        self.last_completion_tokens = int(usage.get("completion_tokens", 0) or 0)
        self.last_total_tokens = int(usage.get("total_tokens", 0) or 0)

    def should_compress(self, prompt_tokens: int = None) -> bool:
        tokens = prompt_tokens if prompt_tokens is not None else self.last_prompt_tokens
        if self.threshold_tokens <= 0:
            return False
        return tokens >= self.threshold_tokens

    def compress(
        self,
        messages: List[Dict[str, Any]],
        current_tokens: int = None,
        focus_topic: str = None,
    ) -> List[Dict[str, Any]]:
        """Compact via virtual-context: ingest turns, compact, reassemble."""
        if not messages:
            return messages

        engine = self._ensure_engine()

        # Step 1: Let virtual-context ingest the full turn history.
        # on_turn_complete processes raw messages into segments and runs
        # compaction if thresholds are hit.
        try:
            vc_messages = self._to_vc_messages(messages)
            engine.on_turn_complete(vc_messages)
        except Exception:
            logger.exception("Virtual Context on_turn_complete failed; returning messages unchanged")
            return messages

        # Step 2: Ask virtual-context to assemble context for the most
        # recent user message (retrieval-augmented).
        last_user_text = self._last_user_text(messages)
        recent_history = self._to_vc_messages(messages[-6:])

        try:
            assembled = engine.on_message_inbound(
                message=last_user_text,
                conversation_history=recent_history,
            )
        except Exception:
            logger.exception("Virtual Context on_message_inbound failed; returning messages unchanged")
            return messages

        if assembled is None or assembled.total_tokens == 0:
            return messages

        # Step 3: Rebuild OpenAI-format message list from assembled context.
        compressed = self._from_assembled(assembled, messages)
        self.compression_count += 1

        logger.info(
            "Virtual Context compaction #%d: %d messages → %d",
            self.compression_count,
            len(messages),
            len(compressed),
        )
        return compressed

    # ── Optional lifecycle hooks ──────────────────────────────────────────

    def on_session_start(self, session_id: str, **kwargs) -> None:
        self._session_id = session_id
        # Eagerly bootstrap so config errors surface early
        try:
            self._ensure_engine()
        except Exception:
            logger.exception("Virtual Context engine failed to initialize")

    def on_session_end(self, session_id: str, messages: List[Dict[str, Any]]) -> None:
        if self._engine is not None:
            try:
                vc_messages = self._to_vc_messages(messages)
                self._engine.on_turn_complete(vc_messages)
            except Exception:
                logger.exception("Virtual Context final ingestion on session end failed")

    def on_session_reset(self) -> None:
        super().on_session_reset()
        self._engine = None
        self._session_id = None

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _to_vc_messages(messages: List[Dict[str, Any]]) -> list:
        """Convert Hermes OpenAI-format dicts to virtual-context Message objects."""
        from virtual_context.types import Message

        result = []
        for msg in messages:
            content = msg.get("content") or ""
            if isinstance(content, list):
                # Flatten multimodal content to text
                parts = [
                    p.get("text", "")
                    for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                ]
                content = " ".join(parts)
            result.append(Message(
                role=msg.get("role", "user"),
                content=content,
            ))
        return result

    @staticmethod
    def _last_user_text(messages: List[Dict[str, Any]]) -> str:
        """Extract the text of the last user message."""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    return content
                # Handle list-form content (multimodal)
                if isinstance(content, list):
                    parts = [
                        p.get("text", "")
                        for p in content
                        if isinstance(p, dict) and p.get("type") == "text"
                    ]
                    return " ".join(parts)
        return ""

    @staticmethod
    def _from_assembled(assembled: Any, original_messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Rebuild an OpenAI-format message list from AssembledContext.

        Strategy: keep the system prompt from original messages (if any),
        inject the assembled context as a system-level summary, then
        append the recent tail.
        """
        result: List[Dict[str, Any]] = []

        # Preserve original system prompt
        if original_messages and original_messages[0].get("role") == "system":
            result.append(original_messages[0])

        # Inject assembled context as a compaction summary
        context_text = ""
        if hasattr(assembled, "messages") and assembled.messages:
            # AssembledContext.messages is a list of Message objects
            for m in assembled.messages:
                role = getattr(m, "role", "system")
                content = getattr(m, "content", "")
                if content:
                    context_text += f"[{role}] {content}\n"

        if context_text.strip():
            result.append({
                "role": "user",
                "content": (
                    "[CONTEXT COMPACTION — REFERENCE ONLY] "
                    "Earlier conversation was compacted by Virtual Context. "
                    "Summary of prior context:\n\n"
                    + context_text.strip()
                ),
            })
            # Maintain role alternation
            result.append({
                "role": "assistant",
                "content": "Understood — I have the compacted context. Continuing.",
            })

        # Append the recent tail (last 6 messages, excluding system)
        tail_start = max(0, len(original_messages) - 6)
        for msg in original_messages[tail_start:]:
            if msg.get("role") != "system":
                result.append(msg)

        return result
