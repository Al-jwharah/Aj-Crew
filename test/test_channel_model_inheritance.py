"""Tests for channel agent model inheritance.

Verifies that ``SessionManager.get_or_create()`` falls back to the global
``agent.model`` config when no explicit model is passed.  This ensures
channel agents (and any other caller that omits ``model=``) inherit the
user's configured model instead of silently defaulting to 'auto' (Sonnet).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from aj_crew.config.loader import AjCrewConfig
from aj_crew.session import SessionManager


@pytest.fixture
def cfg():
    c = AjCrewConfig()
    # The default provider is now ``acp`` (KiroACP/kiro-cli). These tests
    # exercise the ``agent.model`` fallback path, so pin the provider to
    # ``acp`` explicitly to be robust to future default changes.
    c.agent.provider = "acp"
    c.agent.model = "claude-opus-4.6"
    c.session.timeout_secs = 2  # short for testing
    return c


def _capturing_factory(captured: dict):
    """Factory that records kwargs passed to it."""

    def factory(session_key=None, agent=None, channel_id=None, **kwargs):
        captured.update(kwargs)
        m = AsyncMock()
        m.start = AsyncMock()
        m.shutdown = AsyncMock()
        m.context_usage_pct = lambda: 0.0
        m.is_alive.return_value = True
        return m

    return factory


class TestModelFallbackToGlobalConfig:
    """get_or_create() falls back to global model when caller omits it."""

    @pytest.mark.asyncio
    async def test_no_model_uses_global_config(self, cfg):
        """When caller omits model=, factory receives the global model."""
        captured: dict = {}
        mgr = SessionManager(cfg, provider_factory=_capturing_factory(captured))
        await mgr.get_or_create("test-fallback", agent="deep-researcher")
        assert captured["model_override"] == "claude-opus-4.6"
        await mgr.close_all()

    @pytest.mark.asyncio
    async def test_explicit_model_overrides_global(self, cfg):
        """Explicit model= wins over global config."""
        captured: dict = {}
        mgr = SessionManager(cfg, provider_factory=_capturing_factory(captured))
        await mgr.get_or_create("test-explicit", model="claude-haiku")
        assert captured["model_override"] == "claude-haiku"
        await mgr.close_all()

    @pytest.mark.asyncio
    async def test_channel_agent_call_pattern(self, cfg):
        """Mirror the channel.py call: agent name, no model arg."""
        captured: dict = {}
        mgr = SessionManager(cfg, provider_factory=_capturing_factory(captured))
        # This is exactly how run_channel_agent() calls get_or_create
        await mgr.get_or_create(
            "channel:abc:agent1",
            agent="deep-researcher",
            approval_policy="trusted",
        )
        # Without the fix, model_override would be None and kiro-cli
        # would default to 'auto' (Sonnet) for non-ajcrew agents.
        assert captured["model_override"] == "claude-opus-4.6"
        await mgr.close_all()

    @pytest.mark.asyncio
    async def test_ajcrew_agent_uses_global(self, cfg):
        """The default 'ajcrew' agent is excluded from per-agent resolution
        and inherits the global model (it intentionally tracks the global)."""
        captured: dict = {}
        mgr = SessionManager(cfg, provider_factory=_capturing_factory(captured))
        await mgr.get_or_create("ajcrew-sess", agent="ajcrew")
        assert captured["model_override"] == "claude-opus-4.6"
        await mgr.close_all()


class TestResolveNamedAgentModel:
    """Real-file coverage for AjCrewConfig._resolve_named_agent_model.

    Uses the ``agents_dir`` dependency-injection seam to point the resolver at
    a temp directory — real files, no patching.
    """

    def test_reads_model_by_name_field(self, tmp_path):
        # filename stem differs from the name field -> proves the name match
        (tmp_path / "file-stem.json").write_text(
            json.dumps({"name": "foo-agent", "model": "claude-sonnet-3"})
        )
        assert (
            AjCrewConfig._resolve_named_agent_model("foo-agent", agents_dir=tmp_path)
            == "claude-sonnet-3"
        )

    def test_reads_model_by_filename_stem(self, tmp_path):
        (tmp_path / "bar.json").write_text(json.dumps({"model": "claude-haiku-4.5"}))
        assert (
            AjCrewConfig._resolve_named_agent_model("bar", agents_dir=tmp_path)
            == "claude-haiku-4.5"
        )

    def test_returns_empty_when_not_found(self, tmp_path):
        (tmp_path / "bar.json").write_text(json.dumps({"model": "x"}))
        assert AjCrewConfig._resolve_named_agent_model("nope", agents_dir=tmp_path) == ""

    def test_returns_empty_for_empty_agent(self, tmp_path):
        assert AjCrewConfig._resolve_named_agent_model("", agents_dir=tmp_path) == ""

    def test_skips_non_dict_json(self, tmp_path):
        # stem matches "weird" but the content isn't an object -> skipped safely
        (tmp_path / "weird.json").write_text(json.dumps([1, 2, 3]))
        assert AjCrewConfig._resolve_named_agent_model("weird", agents_dir=tmp_path) == ""

    def test_skips_malformed_json_and_finds_valid(self, tmp_path):
        (tmp_path / "broken.json").write_text("{not valid json")
        (tmp_path / "good.json").write_text(json.dumps({"model": "claude-opus-4.8"}))
        assert (
            AjCrewConfig._resolve_named_agent_model("good", agents_dir=tmp_path)
            == "claude-opus-4.8"
        )

    def test_malformed_json_only_returns_empty(self, tmp_path):
        # Only a malformed file present -> json.loads raises, the entry is
        # skipped via the except/continue branch, and the resolver returns "".
        # (Deterministic: no valid file can match first and short-circuit.)
        (tmp_path / "broken.json").write_text("{not valid json")
        assert (
            AjCrewConfig._resolve_named_agent_model("broken", agents_dir=tmp_path) == ""
        )

    def test_match_with_no_model_field_returns_empty(self, tmp_path):
        (tmp_path / "nomodel.json").write_text(json.dumps({"name": "nomodel"}))
        assert (
            AjCrewConfig._resolve_named_agent_model("nomodel", agents_dir=tmp_path) == ""
        )


class TestAgentSpecReadsAreHardened:
    """Both model resolvers must read agent specs through the discovery
    module's hardened reader, not bare ``read_text``: the agents
    directory is user-writable and shared with other tools, so an oversized
    file is refused at the read cap and a link resolving into a sensitive
    path donates nothing."""

    def test_named_resolver_refuses_an_oversized_spec(self, tmp_path, monkeypatch):
        from aj_crew import agent_discovery
        from aj_crew.hooks import FileTooLargeError

        (tmp_path / "huge.json").write_text(json.dumps({"name": "huge", "model": "m"}))
        monkeypatch.setattr(
            agent_discovery,
            "_read_spec_bytes",
            lambda _p: (_ for _ in ()).throw(FileTooLargeError()),
        )
        assert AjCrewConfig._resolve_named_agent_model("huge", agents_dir=tmp_path) == ""

    def test_named_resolver_refuses_a_link_into_a_sensitive_path(
        self, tmp_path, monkeypatch
    ):
        # A directory junction needs no privilege on Windows and resolves
        # through pathlib exactly like a symlink, so the guard is exercised
        # here rather than skipped. The sensitive-path verdict is scoped to
        # the junction's TARGET so the test proves resolution follows the
        # link: a same-named spec OUTSIDE the link must still read fine.
        from aj_crew import agent_discovery
        from conftest import make_dir_link

        outside = tmp_path / "sensitive-outside"
        outside.mkdir()
        (outside / "link.json").write_text(json.dumps({"name": "link", "model": "stolen"}))
        (tmp_path / "direct.json").write_text(json.dumps({"name": "direct", "model": "fine"}))
        make_dir_link(tmp_path / "link", outside)
        monkeypatch.setattr(
            agent_discovery,
            "is_sensitive_path",
            lambda p: "sensitive-outside" in str(p),
        )
        assert AjCrewConfig._resolve_named_agent_model("link", agents_dir=tmp_path) == ""
        assert (
            AjCrewConfig._resolve_named_agent_model("direct", agents_dir=tmp_path)
            == "fine"
        )

    def test_installed_spec_resolver_reads_through_the_hardened_reader(
        self, tmp_path, monkeypatch
    ):
        # The installed ajcrew.json path goes through the same reader: a
        # spec the reader refuses yields no model, and the resolver falls
        # through to the bundled default instead of trusting the file.
        import aj_crew.config.loader as loader_mod
        from aj_crew import agent_discovery
        from aj_crew.hooks import FileTooLargeError

        (tmp_path / "ajcrew.json").write_text(json.dumps({"model": "pinned"}))
        monkeypatch.setattr(loader_mod, "kiro_agents_dir", lambda: tmp_path)
        seen = {}

        def _refusing_read(_path):
            seen["called"] = True
            raise FileTooLargeError()

        monkeypatch.setattr(agent_discovery, "_read_spec_bytes", _refusing_read)
        result = AjCrewConfig._resolve_agent_model()
        assert seen["called"] is True
        assert result != "pinned"
