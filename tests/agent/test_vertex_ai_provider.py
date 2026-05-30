"""Tests for the vertex-ai (Claude-on-Vertex) provider.

Covers the wiring that keeps `vertex-ai` a DISTINCT Claude provider rather
than collapsing into the Gemini `vertex` provider:

  * lazy-install registration of ``anthropic[vertex]`` (``provider.vertex-ai``)
  * ``resolve_vertex_credentials`` env handling
  * ``build_vertex_client`` lazy-ensure + import-error contract
  * the auxiliary ``_try_vertex`` (Gemini) vs ``_try_vertex_ai`` (Claude) split
"""

import sys
import types

import pytest

from tools import lazy_deps


# ---------------------------------------------------------------------------
# Lazy-install registration
# ---------------------------------------------------------------------------


class TestVertexAiLazyDep:
    def test_feature_registered(self):
        assert "provider.vertex-ai" in lazy_deps.LAZY_DEPS

    def test_spec_is_anthropic_vertex_and_safe(self):
        specs = lazy_deps.feature_specs("provider.vertex-ai")
        assert len(specs) == 1
        spec = specs[0]
        # Invariant (not a version snapshot): the anthropic package with the
        # [vertex] extra, a pinned version, and safe for the installer.
        assert spec.startswith("anthropic[vertex]")
        assert lazy_deps._pkg_name_from_spec(spec) == "anthropic"
        assert lazy_deps._spec_is_safe(spec)

    def test_pin_tracks_anthropic_to_avoid_churn(self):
        # provider.vertex-ai and provider.anthropic install the *same* anthropic
        # version, so a user running both doesn't flip-flop the pin on each
        # lazy ensure / `hermes update`.
        va = lazy_deps.feature_specs("provider.vertex-ai")[0]
        an = lazy_deps.feature_specs("provider.anthropic")[0]
        assert lazy_deps._specifier_from_spec(va) == lazy_deps._specifier_from_spec(an)

    def test_install_command_mentions_extra(self):
        cmd = lazy_deps.feature_install_command("provider.vertex-ai")
        assert cmd and "anthropic[vertex]" in cmd


# ---------------------------------------------------------------------------
# Credential resolution
# ---------------------------------------------------------------------------


class TestResolveVertexCredentials:
    def _clear(self, monkeypatch):
        for var in (
            "VERTEX_PROJECT",
            "GOOGLE_CLOUD_PROJECT",
            "GCP_PROJECT_ID",
            "VERTEX_REGION",
        ):
            monkeypatch.delenv(var, raising=False)

    def test_none_when_unset(self, monkeypatch):
        self._clear(monkeypatch)
        from agent.anthropic_adapter import resolve_vertex_credentials

        assert resolve_vertex_credentials() == (None, None)

    def test_vertex_project_with_default_region(self, monkeypatch):
        self._clear(monkeypatch)
        monkeypatch.setenv("VERTEX_PROJECT", "my-proj")
        from agent.anthropic_adapter import resolve_vertex_credentials

        assert resolve_vertex_credentials() == ("my-proj", "us-east5")

    def test_fallback_env_and_region_override(self, monkeypatch):
        self._clear(monkeypatch)
        monkeypatch.setenv("GCP_PROJECT_ID", "fallback-proj")
        monkeypatch.setenv("VERTEX_REGION", "europe-west1")
        from agent.anthropic_adapter import resolve_vertex_credentials

        assert resolve_vertex_credentials() == ("fallback-proj", "europe-west1")


# ---------------------------------------------------------------------------
# Client construction
# ---------------------------------------------------------------------------


class TestBuildVertexClient:
    def test_lazy_ensure_invoked_and_clear_import_error(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            "tools.lazy_deps.ensure",
            lambda feature, **kw: calls.append((feature, kw)),
        )
        # Fake `anthropic` module lacking AnthropicVertex → import fails.
        monkeypatch.setitem(sys.modules, "anthropic", types.ModuleType("anthropic"))

        from agent.anthropic_adapter import build_vertex_client

        with pytest.raises(ImportError) as excinfo:
            build_vertex_client("proj", "us-east5")

        # The lazy installer was consulted (non-interactively) for the right feature.
        assert calls and calls[0][0] == "provider.vertex-ai"
        assert calls[0][1].get("prompt") is False
        # The error tells the user how to install the extra.
        assert "vertex-ai" in str(excinfo.value)
        assert "anthropic[vertex]" in str(excinfo.value)

    def test_builds_client_with_expected_kwargs(self, monkeypatch):
        monkeypatch.setattr("tools.lazy_deps.ensure", lambda *a, **k: None)

        created = {}

        class FakeAnthropicVertex:
            def __init__(self, **kwargs):
                created.update(kwargs)

        fake = types.ModuleType("anthropic")
        fake.AnthropicVertex = FakeAnthropicVertex
        monkeypatch.setitem(sys.modules, "anthropic", fake)

        from agent.anthropic_adapter import build_vertex_client

        client = build_vertex_client("proj-x", "asia-east1")

        assert isinstance(client, FakeAnthropicVertex)
        assert created["project_id"] == "proj-x"
        assert created["region"] == "asia-east1"
        assert "timeout" in created


# ---------------------------------------------------------------------------
# Auxiliary client routing: Gemini (_try_vertex) vs Claude (_try_vertex_ai)
# ---------------------------------------------------------------------------


class TestAuxiliaryVertexSplit:
    def test_try_vertex_ai_is_distinct_from_try_vertex(self):
        from agent import auxiliary_client

        # The merge renamed the Claude path to avoid colliding with the Gemini
        # path; they must remain two separate callables.
        assert auxiliary_client._try_vertex is not auxiliary_client._try_vertex_ai

    def test_try_vertex_ai_returns_none_without_creds(self, monkeypatch):
        for var in ("VERTEX_PROJECT", "GOOGLE_CLOUD_PROJECT", "GCP_PROJECT_ID"):
            monkeypatch.delenv(var, raising=False)
        from agent.auxiliary_client import _try_vertex_ai

        assert _try_vertex_ai() == (None, None)
