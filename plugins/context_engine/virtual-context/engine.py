"""Virtual Context adapter — ContextEngine subclass wrapping VirtualContextEngine.

Translates between Hermes's ContextEngine contract (OpenAI-format message
lists, token tracking, compress/should_compress) and the virtual-context
library's segment/retrieval/compaction API.

Design notes
------------
* **Conversation identity.** virtual-context keys everything (segments, tags,
  facts, paging state) on ``config.conversation_id``, which defaults to a fresh
  random UUID on every config load. We bind it to Hermes's ``session_id`` so a
  conversation's memory is stable across process restarts and isolated from
  other sessions/users. The engine is (re)built whenever the bound session
  changes.

* **Cadence / prompt caching.** The virtual-context *proxy* reassembles context
  on every inbound message because it manages provider cache deferral itself.
  Inside Hermes that would invalidate the per-conversation prompt-cache prefix
  every turn — the one thing Hermes treats as sacred. So we ingest + assemble
  only at compaction time (and flush on session end). virtual-context's
  watermark bookkeeping (``last_completed_turn`` / ``compacted_prefix_messages``)
  makes repeated ``on_turn_complete(full_history)`` calls incremental, so no
  turn is tagged twice and nothing is lost even though ingestion is batched.

* **Context ceiling.** virtual-context's whole quality story ("run a 200K model
  at 60K") depends on *its* lower ``context_window`` triggering compaction
  early. ``update_model`` therefore clamps the tracked ceiling to
  ``config.context_window`` instead of inheriting the model's raw window.
"""

from __future__ import annotations

import copy
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.context_engine import ContextEngine

logger = logging.getLogger(__name__)

# Match the built-in ContextCompressor's delimiters so downstream summary
# detection (``_is_context_summary_content``) and re-compaction recognise the
# injected block as prior-context reference material rather than a fresh turn.
_PRIOR_CONTEXT_HEADER = "[PRIOR CONTEXT — for reference only; not a new message]"
_SUMMARY_DELIMITER = "[END OF PRIOR CONTEXT — COMPACTION SUMMARY BELOW]"


class VirtualContextAdapter(ContextEngine):
    """Thin adapter that delegates to ``VirtualContextEngine``."""

    # Compaction shape (read by run_agent.py's preflight path).
    threshold_percent: float = 0.75
    protect_first_n: int = 2
    protect_last_n: int = 8

    # ── Identity ──────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "virtual-context"

    @staticmethod
    def is_available() -> bool:
        """Reported by discovery so the picker only offers a usable engine.

        The ``virtual_context`` package is an optional dependency; without it
        the engine would silently fall back to head+tail truncation.
        """
        import importlib.util
        return importlib.util.find_spec("virtual_context") is not None

    # ── Construction ──────────────────────────────────────────────────────

    def __init__(self, *, hermes_home: str = "") -> None:
        self._hermes_home = (
            hermes_home
            or os.environ.get("HERMES_HOME")
            or os.path.expanduser("~/.hermes")
        )
        self._config: Optional[Any] = None          # cached VirtualContextConfig template
        self._config_path: Optional[Path] = None
        self._engine: Optional[Any] = None           # VirtualContextEngine (per-session)
        self._engine_conversation_id: Optional[str] = None
        self._session_id: Optional[str] = None
        self._model: str = ""

        # Token tracking (read by run_agent.py)
        self.last_prompt_tokens: int = 0
        self.last_completion_tokens: int = 0
        self.last_total_tokens: int = 0
        self.threshold_tokens: int = 0
        self.context_length: int = 0
        self.compression_count: int = 0

    # ── deepcopy (child agents / plugin-singleton path) ───────────────────

    def __deepcopy__(self, memo):
        """Copy only mutable budget state; leave the heavy engine unbuilt.

        ``agent_init`` deep-copies a registered context engine for each child
        agent. The underlying ``VirtualContextEngine`` holds uncopyable state
        (SQLite connections, an embedding model, provider clients), so a naive
        deepcopy would raise and silently fall back to the built-in compressor.
        We instead hand back a fresh adapter that shares the (immutable) config
        template and rebuilds its own engine lazily, bound to its own session.
        """
        cls = self.__class__
        new = cls.__new__(cls)
        new._hermes_home = self._hermes_home
        new._config = self._config            # shared read-only template
        new._config_path = self._config_path
        new._engine = None                    # rebuilt lazily per session
        new._engine_conversation_id = None
        new._session_id = None
        new._model = self._model
        new.last_prompt_tokens = 0
        new.last_completion_tokens = 0
        new.last_total_tokens = 0
        new.threshold_tokens = self.threshold_tokens
        new.context_length = self.context_length
        new.compression_count = 0
        memo[id(self)] = new
        return new

    # ── Config bootstrap (cheap — no engine build) ────────────────────────

    def _ensure_config(self) -> Any:
        """Load and cache the VirtualContextConfig template (no engine build)."""
        if self._config is not None:
            return self._config

        from virtual_context.config import load_config

        config_path = os.environ.get("VIRTUAL_CONTEXT_CONFIG")
        if config_path:
            self._config_path = Path(config_path)
        else:
            candidates = [
                Path(self._hermes_home) / "virtual-context.yaml",
                Path(self._hermes_home) / "virtual-context" / "virtual-context.yaml",
            ]
            for c in candidates:
                if c.is_file():
                    self._config_path = c
                    break

        try:
            if self._config_path and self._config_path.is_file():
                cfg = load_config(config_path=self._config_path)
                logger.info("virtual-context config loaded from %s", self._config_path)
            else:
                cfg = load_config()
                logger.info("virtual-context using default/auto-discovered config")
        except Exception:
            # A malformed or partially-configured user YAML makes validating
            # load_config raise. Fall back to unvalidated defaults so the
            # engine still works rather than disabling itself entirely.
            logger.exception(
                "virtual-context: config load failed; falling back to defaults"
            )
            try:
                cfg = load_config(config_dict={}, validate=False)
            except Exception:
                logger.exception("virtual-context: default config build failed")
                raise

        self._anchor_storage(cfg)

        if not (cfg.summarization.provider and cfg.summarization.provider in cfg.providers):
            logger.warning(
                "virtual-context: no usable summarization provider configured "
                "(summarization.provider=%r). Compaction will fall back to "
                "head+tail truncation without LLM summaries or fact extraction. "
                "Add a provider under `providers:` and set `summarization.provider` "
                "in virtual-context.yaml to enable full compaction.",
                cfg.summarization.provider,
            )

        self._config = cfg

        # Seed the context ceiling from VC's own window if update_model hasn't
        # run yet (e.g. compress() reached before a model resolution).
        if self.context_length <= 0:
            self.context_length = int(cfg.context_window or 0)
            self.threshold_tokens = int(self.context_length * self.threshold_percent)

        return cfg

    def _anchor_storage(self, cfg: Any) -> None:
        """Force default storage paths under the active HERMES_HOME (profile-safe).

        virtual-context defaults to cwd-relative ``.virtualcontext/...`` paths,
        which would scatter or collide across Hermes profiles and working
        directories. Only rewrite paths the user hasn't explicitly overridden.
        """
        default_sqlite = ".virtualcontext/store.db"
        default_root = ".virtualcontext/store"
        base = Path(self._hermes_home) / "virtual-context"
        try:
            if getattr(cfg.storage, "sqlite_path", "") in ("", default_sqlite):
                cfg.storage.sqlite_path = str(base / "store.db")
            if getattr(cfg.storage, "root", "") in ("", default_root):
                cfg.storage.root = str(base / "store")
            Path(cfg.storage.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            logger.debug("virtual-context: storage path anchoring failed", exc_info=True)

    # ── Conversation identity ─────────────────────────────────────────────

    def _derive_conversation_id(self, session_id: Optional[str]) -> str:
        sid = (session_id or self._session_id or "").strip()
        if not sid:
            return "hermes-default"
        return f"hermes:{sid}"

    # ── Engine bootstrap (per session) ────────────────────────────────────

    def _ensure_engine(self) -> Any:
        """Build (or rebind) the VirtualContextEngine for the current session."""
        conv_id = self._derive_conversation_id(self._session_id)
        if self._engine is not None and self._engine_conversation_id == conv_id:
            return self._engine

        cfg = self._ensure_config()

        from virtual_context.engine import VirtualContextEngine

        # Shallow-copy the template so per-session conversation_id overrides
        # (and any in-engine alias rebinds) never mutate the shared template.
        engine_cfg = copy.copy(cfg)
        engine_cfg.conversation_id = conv_id

        self._close_engine()
        self._engine = VirtualContextEngine(config=engine_cfg)
        self._engine_conversation_id = conv_id
        logger.info(
            "virtual-context engine bound to conversation_id=%s (session=%s)",
            conv_id, self._session_id or "none",
        )
        return self._engine

    def _close_engine(self) -> None:
        if self._engine is not None:
            try:
                self._engine.close()
            except Exception:
                logger.debug("virtual-context engine close failed", exc_info=True)

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
        """Compact via virtual-context: ingest turns, retrieve, rebuild list."""
        if not messages:
            return messages

        try:
            engine = self._ensure_engine()
        except Exception:
            logger.exception(
                "virtual-context: engine init failed; using head+tail truncation"
            )
            return self._rebuild_messages(messages, summary_text="")

        # 1. Ingest the full pre-compaction history. Watermark bookkeeping in
        #    the engine makes this incremental — only new turns are tagged.
        try:
            engine.on_turn_complete(self._to_vc_messages(messages))
        except Exception:
            logger.exception("virtual-context on_turn_complete failed during compaction")

        # 2. Assemble retrieval-augmented context for the latest user message.
        summary_text = ""
        try:
            last_user = self._last_user_text(messages)
            recent = self._to_vc_messages(messages[-self.protect_last_n:])
            assembled = engine.on_message_inbound(
                message=last_user,
                conversation_history=recent,
                model_name=self._model,
                max_context_tokens=self.context_length or None,
            )
            if assembled is not None:
                summary_text = self._assembled_to_text(assembled)
        except Exception:
            logger.exception("virtual-context on_message_inbound failed during compaction")

        result = self._rebuild_messages(messages, summary_text=summary_text)
        self.compression_count += 1
        logger.info(
            "virtual-context compaction #%d: %d messages → %d",
            self.compression_count, len(messages), len(result),
        )
        return result

    # ── Lifecycle hooks ───────────────────────────────────────────────────

    def on_session_start(self, session_id: str, **kwargs) -> None:
        if session_id and session_id != self._session_id:
            # A new session → drop the engine so it rebinds to the new id.
            self._close_engine()
            self._engine = None
            self._engine_conversation_id = None
        self._session_id = session_id
        try:
            self._ensure_engine()
        except Exception:
            logger.exception(
                "virtual-context engine failed to initialize for session %s",
                session_id,
            )

    def on_session_end(self, session_id: str, messages: List[Dict[str, Any]]) -> None:
        if self._engine is not None and messages:
            try:
                self._engine.on_turn_complete(self._to_vc_messages(messages))
            except Exception:
                logger.exception("virtual-context final ingestion on session end failed")
        self._close_engine()

    def on_session_reset(self) -> None:
        super().on_session_reset()
        self._close_engine()
        self._engine = None
        self._engine_conversation_id = None
        self._session_id = None

    # ── Model switch ──────────────────────────────────────────────────────

    def update_model(
        self,
        model: str,
        context_length: int,
        base_url: str = "",
        api_key: str = "",
        provider: str = "",
        api_mode: str = "",
    ) -> None:
        """Clamp the tracked ceiling to VC's configured window.

        The base implementation would set ``context_length`` to the model's
        full window, defeating the point of running the model at a lower
        virtual ceiling. We keep VC's ``context_window`` as the authority
        (never exceeding the model's real window).
        """
        self._model = model or self._model
        ceiling = 0
        try:
            cfg = self._ensure_config()
            ceiling = int(cfg.context_window or 0)
        except Exception:
            logger.debug("virtual-context: config unavailable in update_model", exc_info=True)

        model_window = int(context_length or 0)
        if ceiling > 0 and model_window > 0:
            effective = min(ceiling, model_window)
        else:
            effective = ceiling or model_window

        self.context_length = effective
        self.threshold_tokens = (
            int(self.context_length * self.threshold_percent)
            if self.context_length else 0
        )

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _to_vc_messages(messages: List[Dict[str, Any]]) -> list:
        """Convert Hermes OpenAI-format dicts to virtual-context Message objects.

        Preserves tool calls (in ``raw_content``), tool-result identity
        (``metadata``), and timestamps so virtual-context's tool-chain
        compression and time-scoped recall have the data they rely on.
        """
        from virtual_context.types import Message

        result = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content")
            raw_content = None

            if isinstance(content, list):
                # Multimodal content: keep the structured blocks as raw_content
                # and flatten text for the summary/tag path.
                raw_content = content
                parts = [
                    p.get("text", "")
                    for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                ]
                content = " ".join(p for p in parts if p)

            content = content or ""

            tool_calls = msg.get("tool_calls")
            if tool_calls:
                names = []
                for tc in tool_calls:
                    fn = (tc.get("function") or {}) if isinstance(tc, dict) else {}
                    names.append(fn.get("name") or "tool")
                if not content:
                    content = "[tool call: " + ", ".join(names) + "]"
                raw_content = [{"type": "tool_calls", "tool_calls": tool_calls}]

            metadata = None
            if role == "tool":
                metadata = {
                    "tool_call_id": msg.get("tool_call_id", ""),
                    "name": msg.get("name", ""),
                }

            ts = msg.get("timestamp")
            ts_val = None
            if isinstance(ts, datetime):
                ts_val = ts
            elif isinstance(ts, str) and ts:
                try:
                    ts_val = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except (TypeError, ValueError):
                    ts_val = None

            result.append(Message(
                role=role,
                content=content,
                timestamp=ts_val,
                metadata=metadata,
                raw_content=raw_content,
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
                if isinstance(content, list):
                    parts = [
                        p.get("text", "")
                        for p in content
                        if isinstance(p, dict) and p.get("type") == "text"
                    ]
                    return " ".join(p for p in parts if p)
        return ""

    @staticmethod
    def _assembled_to_text(assembled: Any) -> str:
        """Flatten an AssembledContext into a single reference-context block."""
        parts: List[str] = []
        for attr in ("prepend_text", "core_context", "facts_text"):
            val = getattr(assembled, attr, "") or ""
            if isinstance(val, str) and val.strip():
                parts.append(val.strip())
        tag_sections = getattr(assembled, "tag_sections", None) or {}
        if isinstance(tag_sections, dict):
            for tag, section in tag_sections.items():
                if isinstance(section, str) and section.strip():
                    parts.append(f"## {tag}\n{section.strip()}")
        return "\n\n".join(parts)

    def _find_tail_start(self, messages: List[Dict[str, Any]], head_end: int) -> int:
        """Pick a tail start that lands on a user-turn boundary.

        Starting the tail on a ``tool`` result (or an assistant message whose
        matching tool call was dropped) produces orphaned tool results the
        provider rejects. Walking back to the nearest ``user`` message keeps
        the tail a self-contained run of turns.
        """
        n = len(messages)
        target = max(head_end, n - self.protect_last_n)
        i = target
        while i > head_end and messages[i].get("role") != "user":
            i -= 1
        if head_end <= i < n and messages[i].get("role") == "user":
            return i
        return target

    def _rebuild_messages(
        self,
        messages: List[Dict[str, Any]],
        summary_text: str,
    ) -> List[Dict[str, Any]]:
        """Rebuild an OpenAI-format list: system + compacted summary + recent tail.

        Role-alternation- and tool-orphan-safe: the summary is merged into the
        first tail user message when possible, otherwise inserted as a
        user/assistant pair.
        """
        head: List[Dict[str, Any]] = []
        head_end = 0
        if messages and messages[0].get("role") == "system":
            head.append(messages[0])
            head_end = 1

        tail_start = self._find_tail_start(messages, head_end)
        middle_exists = tail_start > head_end
        has_summary = bool(summary_text and summary_text.strip())

        # Nothing to drop and nothing to inject → leave the list untouched.
        if not middle_exists and not has_summary:
            return messages

        if has_summary:
            body = summary_text.strip()
        else:
            body = "[Earlier conversation turns were compacted and are omitted here.]"
        summary_block = f"{_PRIOR_CONTEXT_HEADER}\n\n{body}\n\n{_SUMMARY_DELIMITER}"

        result: List[Dict[str, Any]] = list(head)
        tail = messages[tail_start:]

        if tail and tail[0].get("role") == "user" and isinstance(tail[0].get("content"), str):
            merged = dict(tail[0])
            merged["content"] = f"{summary_block}\n\n{tail[0].get('content', '')}"
            result.append(merged)
            result.extend(tail[1:])
        else:
            result.append({"role": "user", "content": summary_block})
            result.append({
                "role": "assistant",
                "content": "Understood — I have the compacted context above and will continue.",
            })
            result.extend(tail)

        return result
