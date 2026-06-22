# Virtual Context Adapter — Worked Example

Plugin at `plugins/context_engine/virtual-context/` wrapping the `virtual-context` library as a Hermes context engine.

## Key Architecture Decisions

### Lazy engine construction
`VirtualContextEngine` pulls in torch, sentence-transformers, and SQLite on init. The adapter defers construction to `_ensure_engine()` (called on first `on_session_start` or `compress`), so the plugin module loads instantly and doesn't slow down Hermes startup if not selected.

### Config discovery chain
1. `$VIRTUAL_CONTEXT_CONFIG` env var (explicit path)
2. `~/.hermes/virtual-context.yaml`
3. `~/.hermes/virtual-context/virtual-context.yaml`
4. Auto-discovery via `virtual_context.config.load_config()` (default)

### Message format translation
Hermes uses OpenAI-format dicts (`{"role": "user", "content": "..."}`) everywhere.
Virtual Context uses `virtual_context.types.Message` dataclass (`Message(role="user", content="...")`).

The adapter converts at the boundary in `_to_vc_messages()`:
```python
from virtual_context.types import Message
Message(role=msg.get("role", "user"), content=content)
```

Multimodal content (list-form) is flattened to text before conversion.

### Compress flow
1. Convert messages → VC Message objects
2. Call `engine.on_turn_complete(vc_messages)` — ingests segments, runs compaction if thresholds met
3. Call `engine.on_message_inbound(last_user_text, recent_history)` — retrieval-augmented assembly
4. Rebuild OpenAI-format list from `AssembledContext`: system prompt + compaction summary + recent tail

### AssembledContext shape
```python
assembled.messages: list[Message]  # Retrieved/compacted context
assembled.total_tokens: int        # Token count of assembled content
```

### Error handling pattern
Both `on_turn_complete` and `on_message_inbound` are wrapped in try/except — on failure, messages pass through unchanged. This is critical because Virtual Context depends on an LLM backend (Ollama/Qwen3 for tagging) that may be down.

## Virtual Context dependency chain
`virtual-context` → `sentence-transformers` (all-MiniLM-L6-v2) → `torch` → heavy. Import is ~3-5 seconds on first load. The lazy init pattern avoids paying this cost unless the engine is actually selected.
