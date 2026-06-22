---
name: hermes-plugin-development
description: "Write Hermes plugins: context engines, memory providers, and general plugins. Covers the plugin contracts, discovery mechanisms, registration patterns, and worked examples."
version: 1.0.0
tags: [hermes, plugins, context-engine, memory-provider, extensibility]
related_skills: [hermes-agent]
---

# Hermes Plugin Development

Write plugins that extend Hermes — context engines, memory providers, and general-purpose plugins. Complements the `hermes-agent` skill (which covers tool registration and CLI commands) with deeper coverage of the plugin subsystems.

## When to Use

- Building a new context engine (alternative to LCM/ContextCompressor)
- Building a new memory provider
- Wrapping an external library as a Hermes plugin
- Debugging plugin discovery or registration failures

## Context Engine Plugins

### Contract: `agent.context_engine.ContextEngine` ABC

Required methods:
```python
@property
def name(self) -> str: ...                    # Short identifier
def update_from_response(self, usage: dict)   # Update token tracking from API response
def should_compress(self, prompt_tokens=None)  # Return True if compaction should fire
def compress(self, messages, current_tokens=None, focus_topic=None) -> list[dict]
    # Main entry — receives full OpenAI-format message list, returns compressed list
```

Required attributes (read by `run_agent.py`):
```python
last_prompt_tokens: int = 0
last_completion_tokens: int = 0
last_total_tokens: int = 0
threshold_tokens: int = 0
context_length: int = 0
compression_count: int = 0
threshold_percent: float = 0.75
```

Optional methods:
- `should_compress_preflight(messages)` — cheap pre-API-call check
- `has_content_to_compress(messages)` — guard for `/compress` command
- `on_session_start(session_id, **kwargs)` — load persisted state
- `on_session_end(session_id, messages)` — flush state
- `on_session_reset()` — reset per-session state
- `get_tool_schemas()` / `handle_tool_call(name, args)` — engine-provided tools
- `update_model(model, context_length, ...)` — react to model switch

### Directory Layout

```
plugins/context_engine/<name>/
├── plugin.yaml       # name, version, description (for discovery UI)
├── __init__.py       # register(ctx) entry point
└── engine.py         # ContextEngine subclass
```

### Discovery & Loading Mechanism

`plugins/context_engine/__init__.py` uses `importlib.util.spec_from_file_location` — NOT normal Python imports. This means:
- **Hyphenated directory names work** (e.g. `hermes-lcm`, `virtual-context`)
- Submodules are pre-registered so relative imports (`from .engine import ...`) work
- The loader tries `register(ctx)` first, then falls back to finding a ContextEngine subclass

The `register(ctx)` pattern uses an `_EngineCollector` fake context:
```python
def register(ctx):
    from .engine import MyEngine
    engine = MyEngine(...)
    ctx.register_context_engine(engine)  # Only one engine allowed at a time
```

### Activation

```bash
hermes config set context.engine <plugin-dir-name>
# e.g.: hermes config set context.engine virtual-context
```

The WebUI settings panel also has a context engine picker.

## Pitfalls

1. **External library type mismatches.** When wrapping an external library, check whether it expects its own dataclass types vs raw dicts. Virtual Context's `VirtualContextEngine` expects `Message` dataclass objects (`virtual_context.types.Message`), not OpenAI-format dicts — calling methods with raw dicts causes `AttributeError: 'dict' object has no attribute 'role'`. Always convert at the adapter boundary.

2. **Graceful degradation is mandatory.** The `__init__.py` should catch `ImportError` on the external dependency and `return` from `register()` silently (with a log warning). The engine's `compress()` should catch exceptions from the backing library and return messages unchanged — never crash the conversation loop.

3. **Only one context engine active at a time.** `register_context_engine()` rejects a second registration. If both LCM and your plugin are configured, the first one loaded wins and the second logs an error.

4. **`compress()` must return valid OpenAI-format messages.** The returned list must maintain role alternation (no two consecutive assistant or user messages). Include the system prompt from the original messages if present.

## Reference Files

- `references/virtual-context-adapter.md` — worked example: Virtual Context adapter plugin
