"""The exact bytes every agent-spec writer puts on disk, pinned as golden digests.

Each scenario runs :func:`aj_crew.agent.rebuild_agent_config` on the SHIPPED defaults,
prompts and server registry, pinning only the launcher path, the kiro-cli version and
the SEL writer. Spec files, audit records and sidecar state are normalized and compared
to SHA-256 goldens, so a dropped, reordered or re-typed field fails here even when no
field-level test names it; a mismatch prints the differing content.

The goldens carry POSIX paths and exec bits, so these run off Windows.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Callable

import pytest

import aj_crew.config.paths as paths_mod
from aj_crew import agent, agent_state
from aj_crew.kiro_cli import SPEC_PERMISSIONS_MIN_VERSION

#: One path segment under a normalized root, with the separator run before it: a
#: Windows spec spells ``<TMP>\\bin\\ajcrew`` where POSIX spells ``<TMP>/bin/ajcrew``.
_UNDER_ROOT = re.compile(r"(<TMP>|<HOME>|<PKG>)((?:\\+[^\\\"\s]+)+)")
_SEPARATORS = re.compile(r"\\+")


class _SelRecorder:
    """Stands in for ``sel()``: records each audit call instead of writing it."""

    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = events

    def log_api_access(self, **fields: Any) -> None:
        self._events.append({"api": fields})

    def log(self, event: Any) -> None:
        self._events.append(
            {
                "event": {
                    "event_type": event.event_type,
                    "operation": event.operation,
                    "outcome": event.outcome,
                    "source": event.source,
                    "resources": event.resources,
                    "error": getattr(event, "error", None),
                }
            }
        )


class _Materialized:
    """One rebuild's full output, normalized for comparison."""

    def __init__(
        self, files: dict[str, str], events: list[Any], state: str, unrefreshed: list[str]
    ) -> None:
        self.files = files
        self.events = events
        self.state = state
        self.unrefreshed = unrefreshed

    def digests(self) -> dict[str, Any]:
        return {
            "files": {name: _sha(text) for name, text in sorted(self.files.items())},
            "events": _sha(json.dumps(self.events, sort_keys=True)),
            "state": _sha(self.state),
            "unrefreshed": self.unrefreshed,
        }


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class _Rig:
    """A private agents directory plus the pinned machine-specific inputs."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.tmp = tmp_path
        self.agents = tmp_path / "agents"
        self.agents.mkdir()
        # The mate conductor and worker specs are written to the crewmate folder
        # (``mate_agents_dir``), not here; their bytes are pinned all the same.
        self.mates = tmp_path / "mates" / "agents"
        bindir = tmp_path / "bin"
        bindir.mkdir()
        self.bin = bindir / "ajcrew"
        self.bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.bin.chmod(0o755)
        self.home = Path(os.environ["AJCREW_HOME"])
        self.kiro_mcp = tmp_path / "kiro-global-mcp.json"
        self.hooks_dir = tmp_path / "hooks"
        self.hooks_dir.mkdir()
        self.events: list[dict[str, Any]] = []
        monkeypatch.setattr(agent, "KIRO_AGENTS_DIR", self.agents)
        monkeypatch.setattr(paths_mod, "mate_agents_dir", lambda: self.mates)
        monkeypatch.setattr(agent, "_AJCREW_BIN", str(self.bin))
        monkeypatch.setattr(agent, "_KIRO_MCP_JSON", self.kiro_mcp)
        monkeypatch.setattr(agent, "_DEFAULT_KIRO_HOOKS_DIR", self.hooks_dir)
        monkeypatch.setattr(agent, "sel", lambda: _SelRecorder(self.events))
        monkeypatch.setattr(
            "aj_crew.apps.bridges._mcp_json_path", lambda: self.agents / "ajcrew.json"
        )
        monkeypatch.setattr(
            "aj_crew.kiro_cli.installed_kiro_cli_version",
            lambda: SPEC_PERMISSIONS_MIN_VERSION,
        )

    def executable(self, name: str) -> Path:
        path = self.tmp / "bin" / name
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
        return path

    def write_json(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def config(self, data: dict[str, Any]) -> None:
        self.write_json(self.home / "config.json", data)

    def normalize(self, text: str) -> str:
        """Replace this run's scratch and home roots with labels, in every spelling.

        Roots appear as-is or JSON-escaped once or twice; separators under a root fold
        to ``/``. ``<PKG>`` is the installed package (the prompt names its docs index).
        A root under ``$HOME`` is also spelled ``~/...`` (``skill://`` resources, and the
        Windows scratch home), and both forms fold to one label.
        """
        package = Path(agent.__file__).resolve().parent
        bases = {
            self.tmp: "<TMP>",
            self.tmp.resolve(): "<TMP>",
            self.home: "<HOME>",
            self.home.resolve(): "<HOME>",
            package: "<PKG>",
        }
        # A spec may also write a root forward-slashed (``Path.as_posix()``, as a
        # ``skill://`` resource does), which on Windows differs from ``str()``.
        roots = {str(p): label for p, label in bases.items()}
        roots.update({p.as_posix(): label for p, label in bases.items()})
        for base, label in bases.items():
            try:
                relative = base.relative_to(Path.home())
            except ValueError:
                continue
            roots[f"~/{relative.as_posix()}"] = label
            roots[f"~/{relative}"] = label
        spellings: dict[str, str] = {}
        for root, label in roots.items():
            once = json.dumps(root)[1:-1]
            for spelled in (root, once, json.dumps(once)[1:-1]):
                spellings[spelled] = label
        for spelling in sorted(spellings, key=len, reverse=True):
            text = text.replace(spelling, spellings[spelling])
        return _UNDER_ROOT.sub(lambda m: m.group(1) + _SEPARATORS.sub("/", m.group(2)), text)

    def snapshot(self) -> _Materialized:
        files = {
            p.name: self.normalize(p.read_text(encoding="utf-8"))
            for folder in (self.agents, self.mates)
            if folder.is_dir()
            for p in sorted(folder.iterdir())
            if p.is_file() and not p.name.startswith(".")
        }
        state_path = agent_state._state_path()
        state = state_path.read_text(encoding="utf-8") if state_path.is_file() else ""
        if state:
            # The worker's mirror bookkeeping records the default spec's file identity
            # and content fingerprint, both of which carry this run's scratch paths. What
            # is contractual is that they describe the default spec now on disk.
            parsed = json.loads(state)
            # The dashboard-author ownership digest is the SHA-256 of the installed spec's
            # bytes, which carry this run's scratch paths (the ajcrew-core launcher). What
            # is contractual is that it equals the digest of the dashboard-author spec now on
            # disk -- so fold it to a stable label when it does, exactly as the worker's
            # mirror bookkeeping below is folded.
            da_file = self.agents / "ajcrew-dashboard-author.json"
            da_digest = None
            if da_file.is_file():
                da_digest = agent_state.spec_digest(json.loads(da_file.read_text(encoding="utf-8")))
            for entry in parsed.values():
                if not isinstance(entry, dict):
                    continue
                if da_digest is not None and entry.get("managed_digest") == da_digest:
                    entry["managed_digest"] = "<DASHBOARD-AUTHOR-DIGEST>"
                if entry.get("mirrored_stat") == agent.default_spec_identity():
                    entry["mirrored_stat"] = "<DEFAULT-SPEC-IDENTITY>"
                if entry.get("mirrored_from") == agent.default_spec_fingerprint():
                    entry["mirrored_from"] = "<DEFAULT-SPEC-FINGERPRINT>"
            state = json.dumps(parsed, indent=2, sort_keys=True)
        events = json.loads(self.normalize(json.dumps(self.events, sort_keys=True, default=str)))
        unrefreshed = sorted(agent._fork_refresh_failed)
        return _Materialized(files, events, self.normalize(state), unrefreshed)


# ── scenarios ────────────────────────────────────────────────────────────────


def _fresh(rig: _Rig) -> dict[str, Any]:
    """A first install: no spec on disk, no MCP sources, no user config."""
    return {}


def _customized(rig: _Rig) -> dict[str, Any]:
    """An existing spec a user has customized, with every MCP source populated."""
    tool = rig.executable("some-mcp")
    rig.write_json(
        rig.agents / "ajcrew.json",
        {
            "name": "ajcrew",
            "description": "customized",
            "model": "claude-opus-4.6-1m",
            "prompt": "file:///somewhere/else/prompt.md",
            "tools": ["fs_read", "@ajcrew-cron", "@ajcrew-core", "@user-srv", "@gone/tool"],
            "allowedTools": ["fs_read", "@ajcrew-core", "@user-srv/do_it", "@gone/tool"],
            "resources": [],
            "toolsSettings": {
                "execute_bash": {
                    "deniedCommands": ["rm -rf /"],
                    "autoAllowReadonly": True,
                    "allowedCommands": ["ls"],
                },
                "subagent": {
                    "availableAgents": ["ajcrew-worker", "review-*"],
                    "trustedAgents": ["ajcrew-worker"],
                },
                "fs_write": {"allowedPaths": ["~/work"]},
            },
            "mcpServers": {
                "ajcrew-cron": {
                    "command": "/stale/ajcrew",
                    "args": ["mcp-cron"],
                    "timeout": 90000,
                    "url": "http://stale",
                    "env": {"FOO": "bar", "HOME": "/elsewhere", "PATH": "/x"},
                    "autoApprove": ["cron_list"],
                },
                "user-srv": {"command": str(tool), "args": ["--serve"], "disabledTools": ["x"]},
            },
            "hooks": {"preToolUse": [{"command": "/bin/true"}]},
            "unknownTopLevel": {"kept": True},
        },
    )
    rig.write_json(
        rig.kiro_mcp,
        {
            "mcpServers": {
                "global-srv": {"command": str(tool), "args": ["g"], "timeout": 5},
                "npm:@scope/pkg": {"command": str(tool), "args": ["scoped"]},
                "missing-bin": {"command": "definitely-not-on-path-b08", "args": []},
                "no-command": {"args": ["x"]},
                "muted-srv": {"command": str(tool), "disabled": True},
                "remote-srv": {
                    "url": "https://mcp.example.test/mcp",
                    "oauth": {"scopes": ["read"], "clientId": "cid"},
                },
            }
        },
    )
    rig.write_json(
        rig.home / "mcp.json",
        {
            "mcpServers": {
                "store-srv": {"command": str(tool), "args": ["store"], "env": {"A": "1"}},
                "global-srv": {"env": {"B": "2"}},
            }
        },
    )
    rig.write_json(rig.home / "agent.json", {"toolsSettings": {"custom_tool": {"k": "v"}}})
    return {}


def _governed(rig: _Rig) -> dict[str, Any]:
    """The customized install under a ceiling that denies some auto-approvals."""
    _customized(rig)
    return {
        "may_auto_approve": lambda ref: ref
        not in {"fs_read", "@ajcrew-core", "@global-srv", "@ajcrew-core/select_crew"}
    }


def _clean_over_customized(rig: _Rig) -> dict[str, Any]:
    """A ``--clean`` rebuild over the customized install."""
    _customized(rig)
    return {"clean": True}


def _user_hooks(rig: _Rig) -> dict[str, Any]:
    """Explicit hooks in both spec shapes plus an autoimported script."""
    guard = rig.executable("guard.sh")
    script = rig.hooks_dir / "audit-post.sh"
    script.write_text("#!/bin/sh\n# matcher: fs_write\nexit 0\n", encoding="utf-8")
    script.chmod(0o755)
    off = rig.hooks_dir / "off-pre.sh"
    off.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    off.chmod(0o755)
    rig.config(
        {
            "agent": {
                "kiro_hooks": [
                    {
                        "name": "guard",
                        "trigger": "PreToolUse",
                        "matcher": "execute_bash",
                        "action": {"type": "command", "command": str(guard)},
                    },
                    {
                        "trigger": "PostFileSave",
                        "action": {"type": "command", "command": str(guard)},
                    },
                    {
                        "trigger": "Stop",
                        "enabled": False,
                        "action": {"type": "command", "command": str(off)},
                    },
                    {"trigger": "nope", "action": {"type": "command", "command": "x"}},
                ],
                "kiro_hooks_autoimport": True,
            }
        }
    )
    return {}


def _object_hooks(rig: _Rig) -> dict[str, Any]:
    """The object-of-arrays hook shape, with the rejections it audits."""
    guard = rig.executable("guard2.sh")
    rig.config(
        {
            "agent": {
                "kiro_hooks": {
                    "preToolUse": [
                        {"command": str(guard), "matcher": "fs_*"},
                        {"command": str(guard), "matcher": "fs_*"},
                        {"command": "relative.sh"},
                        {"matcher": "x"},
                    ],
                    "fileEdited": [{"command": str(guard)}],
                    "bogusEvent": [{"command": str(guard)}],
                    "stop": "not-a-list",
                },
                "kiro_hooks_autoimport": False,
            }
        }
    )
    return {}


def _registry_mode(rig: _Rig) -> dict[str, Any]:
    """An install the operator declared registry-governed."""
    rig.config({"agent": {"mcp_registry_mode": True, "model": "claude-sonnet-4.5"}})
    return {}


def _forks(rig: _Rig) -> dict[str, Any]:
    """Two private template copies: one corroborated by a crew binding, one orphaned."""
    from aj_crew.config.loader import AjCrewAgentConfig, AjCrewConfig

    cfg = AjCrewConfig()
    cfg.agents = {"my-crew": AjCrewAgentConfig(kiro_agent="my-crew")}
    cfg.save()
    for name in ("my-crew", "orphan-crew"):
        rig.write_json(
            rig.agents / f"{name}.json",
            {
                "name": name,
                "prompt": "file:///old-home/.kiro/crew/prompt.md",
                "tools": ["fs_read", "@ajcrew-core"],
                "allowedTools": ["fs_read", "@ajcrew-core", 7],
                "toolsSettings": {
                    "execute_bash": {"deniedCommands": ["rm"]},
                    "subagent": {"availableAgents": "not-a-list"},
                },
                "mcpServers": {"ajcrew-core": {"command": "/old", "autoApprove": ["x"]}},
                "hooks": {"old": "hook"},
            },
        )
        agent_state.set_fork_info(name, forked_from="ajcrew", private_to=name)
    return {"may_auto_approve": lambda ref: ref != "@ajcrew-core"}


SCENARIOS: dict[str, Callable[[_Rig], dict[str, Any]]] = {
    "fresh": _fresh,
    "customized": _customized,
    "governed": _governed,
    "clean_over_customized": _clean_over_customized,
    "user_hooks": _user_hooks,
    "object_hooks": _object_hooks,
    "registry_mode": _registry_mode,
    "forks": _forks,
}


def materialize(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str) -> _Materialized:
    """Run one scenario's rebuild in a private rig and return its normalized output."""
    rig = _Rig(tmp_path, monkeypatch)
    options = SCENARIOS[scenario](rig)
    if "may_auto_approve" in options:
        monkeypatch.setattr(agent, "_may_auto_approve", options["may_auto_approve"])
    agent.rebuild_agent_config(clean=options.get("clean", False))
    return rig.snapshot()


#: Digests recorded from the pre-split ``aj_crew.agent``. See the module docstring.
GOLDEN: dict[str, dict[str, Any]] = {
    "clean_over_customized": {
        "events": "5327e559cec71cc91726e68729517c1b5ee0005d5d05cf239fb0f92ed7a18e0b",
        "files": {
            "ajcrew-conductor.json": "56b4bde8004a2bb8ed7f26a2737ebc1d91a0fb847d8d0e0f96aaaa17e8b7e4e1",
            "ajcrew-dashboard-author.json": "e62c0b9863e606b50eb5f6f4b8577b32f09b0ed84684cd9edda9b149fb2b3546",
            "ajcrew-dashboard-manager.json": "e9855d36b2ae02a3d71231427cae9b93cb2b4f7e188e4981f2998d74b940ce17",
            "ajcrew-guest.json": "11da31cbe7a028d482227e6538cc2d0956d4f4a25055c6a2236b42cf0f113f70",
            "ajcrew-heartbeat.json": "164890d09770d686d129f47c9ead362bdc58b2991762e3a0dc779980a23ecb18",
            "ajcrew-knowledge.json": "561d4cb86d2a375ec1df2e20f5a317a25ea71de25ae308c620d2cc3ae7b5ca09",
            "ajcrew-ledger-conductor.json": "c66919e730789290d6782d6996c2395d708e042437ab591f2faa0f4324ee1215",
            "ajcrew-lite.json": "239bc304dd7f9d3aa9f1fb44a6747eb32c8904a15acd8c3b099e1144f8bb5348",
            "ajcrew-mate-conductor.json": "2f4bbe3698617d6b2f8900e74c9a69ad796814a9aeff325934d6ff6373099f66",
            "ajcrew-mate-worker.json": "b162f0690e3325b89a987327d8d003bc908cedbcbb368fcbb8e1a6fc371eb4d2",
            "ajcrew-pipeline-conductor.json": "3c59e01412cfaeedd2f794029d0776f41aa39a6a916df777476fcde102fd194d",
            "ajcrew-research.json": "0e7c3e0a07c2a0683c944edd4f202159eb7419e36c00627cd9ef8b2780128c87",
            "ajcrew-security-conductor.json": "5c8b08420fad3d7336b5d8994e5ad3cbe545faf8769b776f05c92adaa457f555",
            "ajcrew-team-lead.json": "0612c88691f5abfd08757251da30a5b4aca3666187cf2b4b89f7eb37afb0cbfe",
            "ajcrew-worker.json": "bc7965e486c25c733e2465991e4ae28fe6b48e5fe86102ab43e2ab3278ab2250",
            "ajcrew.json": "872c28fa6406792ea4af4ab34ad896b662dc45b8f2a2f7248d1963a13822332a",
            "ajcrew.lock": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        },
        "state": "4d814632fa2447ebd370de10f6b7d1ed2982df59aff58e1dafff73fc036fe818",
        "unrefreshed": [],
    },
    "customized": {
        "events": "f402d692ede2facbd700b42a5f5b015a45681d75f21e33c5fa8704802ff6e283",
        "files": {
            "ajcrew-conductor.json": "56b4bde8004a2bb8ed7f26a2737ebc1d91a0fb847d8d0e0f96aaaa17e8b7e4e1",
            "ajcrew-dashboard-author.json": "e62c0b9863e606b50eb5f6f4b8577b32f09b0ed84684cd9edda9b149fb2b3546",
            "ajcrew-dashboard-manager.json": "e9855d36b2ae02a3d71231427cae9b93cb2b4f7e188e4981f2998d74b940ce17",
            "ajcrew-guest.json": "11da31cbe7a028d482227e6538cc2d0956d4f4a25055c6a2236b42cf0f113f70",
            "ajcrew-heartbeat.json": "164890d09770d686d129f47c9ead362bdc58b2991762e3a0dc779980a23ecb18",
            "ajcrew-knowledge.json": "561d4cb86d2a375ec1df2e20f5a317a25ea71de25ae308c620d2cc3ae7b5ca09",
            "ajcrew-ledger-conductor.json": "c66919e730789290d6782d6996c2395d708e042437ab591f2faa0f4324ee1215",
            "ajcrew-lite.json": "239bc304dd7f9d3aa9f1fb44a6747eb32c8904a15acd8c3b099e1144f8bb5348",
            "ajcrew-mate-conductor.json": "2f4bbe3698617d6b2f8900e74c9a69ad796814a9aeff325934d6ff6373099f66",
            "ajcrew-mate-worker.json": "b162f0690e3325b89a987327d8d003bc908cedbcbb368fcbb8e1a6fc371eb4d2",
            "ajcrew-pipeline-conductor.json": "3c59e01412cfaeedd2f794029d0776f41aa39a6a916df777476fcde102fd194d",
            "ajcrew-research.json": "0e7c3e0a07c2a0683c944edd4f202159eb7419e36c00627cd9ef8b2780128c87",
            "ajcrew-security-conductor.json": "5c8b08420fad3d7336b5d8994e5ad3cbe545faf8769b776f05c92adaa457f555",
            "ajcrew-team-lead.json": "0612c88691f5abfd08757251da30a5b4aca3666187cf2b4b89f7eb37afb0cbfe",
            "ajcrew-worker.json": "f4a25c9ed51702e22a40dc81df8298b55c1b52dcfc95d2e23f6e60e03afa62bb",
            "ajcrew.json": "cbc91457e71bccc02212f6650c092e587976c8c8326e0495d795ed058a96306e",
            "ajcrew.lock": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        },
        "state": "f93d34eb781671d6955c8b6f9485edc04d9b1bf9f1c906ef5188e4f892046b91",
        "unrefreshed": [],
    },
    "forks": {
        "events": "0c7042305367f1140ff83d6e882e84c69f6e7d0c3c302afd550ed61b9649455d",
        "files": {
            "ajcrew-conductor.json": "5677ea55e58ba688ecb6fa483cefb5d5dda33a32a0bcb2cdcf072a34d6ef0cc6",
            "ajcrew-dashboard-author.json": "27bf8f79e5f4b8ce0b84fc47a9ca498f305624392e607eb5970d48c4e16f91d6",
            "ajcrew-dashboard-manager.json": "9a3a3a7c2cee98d5fca83c30e9daf7183c596f77840a7775b865efc44524b425",
            "ajcrew-guest.json": "11da31cbe7a028d482227e6538cc2d0956d4f4a25055c6a2236b42cf0f113f70",
            "ajcrew-heartbeat.json": "164890d09770d686d129f47c9ead362bdc58b2991762e3a0dc779980a23ecb18",
            "ajcrew-knowledge.json": "561d4cb86d2a375ec1df2e20f5a317a25ea71de25ae308c620d2cc3ae7b5ca09",
            "ajcrew-ledger-conductor.json": "9ef38c469e7239d0bd61c1b66a8ab9bec4330af812ff46ada2aaab1f3f53ab25",
            "ajcrew-lite.json": "239bc304dd7f9d3aa9f1fb44a6747eb32c8904a15acd8c3b099e1144f8bb5348",
            "ajcrew-mate-conductor.json": "44b3b12d2ed7300eaeed3e2f68b73ac08b2d297aca2d6574525a40ed73c4cf37",
            "ajcrew-mate-worker.json": "2d0e29384838e96870bf81980d26fcc6b7b80a4250c0c6526399384e38650c22",
            "ajcrew-pipeline-conductor.json": "3471865e7f8e2c3761dda2fa94ee526b0bcb63752d1982d9f1a22360f6d7125d",
            "ajcrew-research.json": "5f9adbaa5c3384522df3479bd4603684c545c49f8f318bdb9b2f82c6f88ed967",
            "ajcrew-security-conductor.json": "1fc8aacb191610fb14410beb95250e99b3f42f78b3be43f64615b49d43fc7624",
            "ajcrew-team-lead.json": "a09e70cc233b2eed2944479d0b10f09ace2ada45eece302cbf0ff757661a823e",
            "ajcrew-worker.json": "7c5e11b5845439517580cb2a2c594932885ab283649e6190f76ce26b2a1e1700",
            "ajcrew.json": "587d086afa5f979742ffab00e665d1d543d4c5f620b86ea5492abb0355dd95f4",
            "ajcrew.lock": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "my-crew.json": "8990263fd58796a13c522548a5af5ed997b158ad69bb68f3be4cc3719468357c",
            "orphan-crew.json": "a2687f313680fcde3bb2740a08ea067638aa4e5a23a7d93f3f7f3ba6bb7b777b",
        },
        "state": "35e75b1d710e5527f99ee10865f0be40ef1c717d5dadaf904e8c81014efbee39",
        "unrefreshed": ["orphan-crew"],
    },
    "fresh": {
        "events": "e874cf15928807be7a552ad74f8a49658f6f4bf9280a2d0bab78d535a813a015",
        "files": {
            "ajcrew-conductor.json": "5677ea55e58ba688ecb6fa483cefb5d5dda33a32a0bcb2cdcf072a34d6ef0cc6",
            "ajcrew-dashboard-author.json": "27bf8f79e5f4b8ce0b84fc47a9ca498f305624392e607eb5970d48c4e16f91d6",
            "ajcrew-dashboard-manager.json": "e9855d36b2ae02a3d71231427cae9b93cb2b4f7e188e4981f2998d74b940ce17",
            "ajcrew-guest.json": "11da31cbe7a028d482227e6538cc2d0956d4f4a25055c6a2236b42cf0f113f70",
            "ajcrew-heartbeat.json": "164890d09770d686d129f47c9ead362bdc58b2991762e3a0dc779980a23ecb18",
            "ajcrew-knowledge.json": "561d4cb86d2a375ec1df2e20f5a317a25ea71de25ae308c620d2cc3ae7b5ca09",
            "ajcrew-ledger-conductor.json": "9ef38c469e7239d0bd61c1b66a8ab9bec4330af812ff46ada2aaab1f3f53ab25",
            "ajcrew-lite.json": "239bc304dd7f9d3aa9f1fb44a6747eb32c8904a15acd8c3b099e1144f8bb5348",
            "ajcrew-mate-conductor.json": "eecef244ddeb302be579fcb65b79216801e17dce86dba05290059b8869047614",
            "ajcrew-mate-worker.json": "fb1387c1002ac2a70083e5f5b8ea54bc4a543b2e486433eb06f700e31ce644bb",
            "ajcrew-pipeline-conductor.json": "3471865e7f8e2c3761dda2fa94ee526b0bcb63752d1982d9f1a22360f6d7125d",
            "ajcrew-research.json": "0c6c4f3ee6d7d188eab4782e5a5b869c8f019fc5f77bc7d68bca711476a4527c",
            "ajcrew-security-conductor.json": "1fc8aacb191610fb14410beb95250e99b3f42f78b3be43f64615b49d43fc7624",
            "ajcrew-team-lead.json": "3d3dac9c3943bcc79225a005322d2dbb6391d548a3c9d7231dab666b3a8bd47a",
            "ajcrew-worker.json": "976948b9b5ec6b4267418738ecf98a3cf72f2d21c401e56b284dea420a448266",
            "ajcrew.json": "c06a90656b5e18b442d59a3886c716f0993ea7c723619fbb10f999f07d0093bd",
            "ajcrew.lock": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        },
        "state": "4d814632fa2447ebd370de10f6b7d1ed2982df59aff58e1dafff73fc036fe818",
        "unrefreshed": [],
    },
    "governed": {
        "events": "a33e2dd4c2ee46b3a9cffceeca14b6d7cf4fdbd4a0d6c65f460cd0989db3819b",
        "files": {
            "ajcrew-conductor.json": "8b6daa010352cbb5517475afa092c7771f9c60f41234dba3ae5112b6db3c3ceb",
            "ajcrew-dashboard-author.json": "e62c0b9863e606b50eb5f6f4b8577b32f09b0ed84684cd9edda9b149fb2b3546",
            "ajcrew-dashboard-manager.json": "e9855d36b2ae02a3d71231427cae9b93cb2b4f7e188e4981f2998d74b940ce17",
            "ajcrew-guest.json": "11da31cbe7a028d482227e6538cc2d0956d4f4a25055c6a2236b42cf0f113f70",
            "ajcrew-heartbeat.json": "164890d09770d686d129f47c9ead362bdc58b2991762e3a0dc779980a23ecb18",
            "ajcrew-knowledge.json": "561d4cb86d2a375ec1df2e20f5a317a25ea71de25ae308c620d2cc3ae7b5ca09",
            "ajcrew-ledger-conductor.json": "2385f858a2e307d05a1a14cb62c699352871936f758b8bd6d4ae03aebee9ebae",
            "ajcrew-lite.json": "239bc304dd7f9d3aa9f1fb44a6747eb32c8904a15acd8c3b099e1144f8bb5348",
            "ajcrew-mate-conductor.json": "43ae67ee9906bfff579b97e0c5bf06209a1a087371226f0e6148a52be19665e6",
            "ajcrew-mate-worker.json": "19a70f684346dc4b92e2d25cbfb377beb30c0bbbd6a36c8b71853acb023fa395",
            "ajcrew-pipeline-conductor.json": "3c59e01412cfaeedd2f794029d0776f41aa39a6a916df777476fcde102fd194d",
            "ajcrew-research.json": "95c318f53a62472e074e955253022635264b2fcf5e6ce8a129d46617fec6cd41",
            "ajcrew-security-conductor.json": "5c8b08420fad3d7336b5d8994e5ad3cbe545faf8769b776f05c92adaa457f555",
            "ajcrew-team-lead.json": "511ac36c55280b4ee87c78d06ccb539ac95656b5d920ab0542e5f114824c3dbd",
            "ajcrew-worker.json": "7a138b19efd551f893cd86a09dac67ecfcf169ea3170ff07cffa9c34132fb360",
            "ajcrew.json": "94f449c81738f88d1dc2866c2c89398ea36191b0764de075d32b84dd3c84354b",
            "ajcrew.lock": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        },
        "state": "f93d34eb781671d6955c8b6f9485edc04d9b1bf9f1c906ef5188e4f892046b91",
        "unrefreshed": [],
    },
    "object_hooks": {
        "events": "4f348e0a2df05172ef6caa8daf282e4e4b13e6033010dbd83fbccd4915fc4b2f",
        "files": {
            "ajcrew-conductor.json": "ce2df6dbe1030bb1d983189798e6407cd414dea195ec63353cb4ec0160fe0734",
            "ajcrew-dashboard-author.json": "2f35eb13a3c6f8df1f5aea55f3f50813eaa183311b6cca259c31c37c158c6db3",
            "ajcrew-dashboard-manager.json": "e9855d36b2ae02a3d71231427cae9b93cb2b4f7e188e4981f2998d74b940ce17",
            "ajcrew-guest.json": "11da31cbe7a028d482227e6538cc2d0956d4f4a25055c6a2236b42cf0f113f70",
            "ajcrew-heartbeat.json": "164890d09770d686d129f47c9ead362bdc58b2991762e3a0dc779980a23ecb18",
            "ajcrew-knowledge.json": "561d4cb86d2a375ec1df2e20f5a317a25ea71de25ae308c620d2cc3ae7b5ca09",
            "ajcrew-ledger-conductor.json": "90b6fbb37140602585264fdf4957bb31b5649605d0eee2334a572ccd5dd55596",
            "ajcrew-lite.json": "239bc304dd7f9d3aa9f1fb44a6747eb32c8904a15acd8c3b099e1144f8bb5348",
            "ajcrew-mate-conductor.json": "44cb2bf1f4a6a879609ec311b1c13012d47023c115b709e5078b08b7c14f7c44",
            "ajcrew-mate-worker.json": "311bfd6c9888417fcd2424db0e50a42dfa8afd324c55a9eb884842533703e8e6",
            "ajcrew-pipeline-conductor.json": "46f77324634233aa0efbbf9860b62b32398498ad88716257499ab56c8a2fa21d",
            "ajcrew-research.json": "188779b6cdd2f4ff3b8db795495c4796c767fa217e821c3e079724b68cea2b28",
            "ajcrew-security-conductor.json": "941c54734ffca66a3a04abfb85254242275d22c0942da495c4f51b12d71a61a0",
            "ajcrew-team-lead.json": "7a084e52af2bd5a61274c4f4452e24b6a40d64ea4bb501e1fec3f6e59c9640a9",
            "ajcrew-worker.json": "3ec6d8634b3c92bb3ed535e84a19fe1b43f8bce80b84d105bf98f56668ad2e0b",
            "ajcrew.json": "c95051134a31128918e4db03ba61e9e3d588456cc79407da9c644edb5f876720",
            "ajcrew.lock": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        },
        "state": "4d814632fa2447ebd370de10f6b7d1ed2982df59aff58e1dafff73fc036fe818",
        "unrefreshed": [],
    },
    "registry_mode": {
        "events": "e874cf15928807be7a552ad74f8a49658f6f4bf9280a2d0bab78d535a813a015",
        "files": {
            "ajcrew-conductor.json": "d03ccabebb6bad97b4479e9f6b93487b40e54240751c0f87b57f99de73f31683",
            "ajcrew-dashboard-author.json": "fbae4aee71a75d7edd5e43defc1196921c25749f94522e626ba2258271941302",
            "ajcrew-dashboard-manager.json": "1e2a8f098730e3a0002821106f8d0ebed8efab9d63f8d01fbdb23e2cb644fd7d",
            "ajcrew-guest.json": "be513c62cea96d01b981978e44564ae15dc31b96eda4337a8c3df05580eb3e99",
            "ajcrew-heartbeat.json": "8c93be23c60d8a46498bccaf152292c1305003e1c8f798dc486b0b4135cf8f8e",
            "ajcrew-knowledge.json": "b7f9aab22f1d9606b8b8a19a8e92e19715368b3828938f5fec38d8bbea5f4bbd",
            "ajcrew-ledger-conductor.json": "ea1892eb513cc423f05b22de5f081e421233f0c84e52182ea1c0fb6dbe60f942",
            "ajcrew-lite.json": "239bc304dd7f9d3aa9f1fb44a6747eb32c8904a15acd8c3b099e1144f8bb5348",
            "ajcrew-mate-conductor.json": "d24c24e7464a59b2a7b5695fc83a69f141883b4d27faab52e6c06aa753bdf96a",
            "ajcrew-mate-worker.json": "32fb540893f0667be788f5c6c899fcf04124a45da75b1634786b5abcebef7ba5",
            "ajcrew-pipeline-conductor.json": "16e7eafbf5065b8a677d63bf8c4bce679869a31efa53abed3738919e09caf03c",
            "ajcrew-research.json": "85b8df1487240cdb0000efd9b0f87da3ffec84a9d5e753d029382853a6398131",
            "ajcrew-security-conductor.json": "2be50ed5faf0a3e64b63f8269b56b7ea1f81e97d21aa3e849b81bf925a53d69f",
            "ajcrew-team-lead.json": "d34938651c38e5fcd5d2ceb94dd0d9d8f9c2f35fd22c3ebfb9d6489075082e71",
            "ajcrew-worker.json": "6cfbb8040b17eb3cb07f53bae414717910b694f05f46585d51417ec367afe05c",
            "ajcrew.json": "c6bdc37cf9c3f4d65553964392fd7b0478c00aed4ec914d1a1e3d1ec96b79436",
            "ajcrew.lock": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        },
        "state": "4d814632fa2447ebd370de10f6b7d1ed2982df59aff58e1dafff73fc036fe818",
        "unrefreshed": [],
    },
    "user_hooks": {
        "events": "a75aa2ab11e5b48451c13614e421b98b664deb094d289819c8a7d7cfe4bd9970",
        "files": {
            "ajcrew-conductor.json": "0e9f3d4645f0494b874e06f77c465de145e8630b8950e2906a9aa8960df9eafa",
            "ajcrew-dashboard-author.json": "1cf22a94f45717c5a188b7e6714f14e1256e86efe79093731b8bc2eec6507002",
            "ajcrew-dashboard-manager.json": "e9855d36b2ae02a3d71231427cae9b93cb2b4f7e188e4981f2998d74b940ce17",
            "ajcrew-guest.json": "11da31cbe7a028d482227e6538cc2d0956d4f4a25055c6a2236b42cf0f113f70",
            "ajcrew-heartbeat.json": "164890d09770d686d129f47c9ead362bdc58b2991762e3a0dc779980a23ecb18",
            "ajcrew-knowledge.json": "561d4cb86d2a375ec1df2e20f5a317a25ea71de25ae308c620d2cc3ae7b5ca09",
            "ajcrew-ledger-conductor.json": "3802d18f52402bd2ab7bdc8740303a97073dded3bef87a3deb86a09bbbb3437f",
            "ajcrew-lite.json": "239bc304dd7f9d3aa9f1fb44a6747eb32c8904a15acd8c3b099e1144f8bb5348",
            "ajcrew-mate-conductor.json": "0b1864b037a012f5c6e0bac2b5328e0c6236904cb02b09b0ac460c19e30266ad",
            "ajcrew-mate-worker.json": "7563b10e0392c7c132ae9bc602537e1aaca1ab8347e7df18875e1a882f2bb086",
            "ajcrew-pipeline-conductor.json": "930fdde07ed819cdcb6be857da7d68f9283b1790ca4b43748abffc0a6fb9c07f",
            "ajcrew-research.json": "5303cf5374cc8f823cc92ef4391168cd938e3cbd4de421958410537fe94004be",
            "ajcrew-security-conductor.json": "a92ea456fe31f85519a9ad1deb142861ab0619ffdffde419d430825b3e725952",
            "ajcrew-team-lead.json": "7a92e15ca9b665cb33ef3fe601b917cb8daa245a92973d378f01e0cd57dd4a63",
            "ajcrew-worker.json": "71674f32fbacc20a64985edd27b2ae0195bf7fd5d151d7dcd0d09b42aca96c1f",
            "ajcrew.json": "0aafd9ddea759e8245da119b84e90fa472710a081a12d94cd1233fc599b14535",
            "ajcrew.lock": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        },
        "state": "4d814632fa2447ebd370de10f6b7d1ed2982df59aff58e1dafff73fc036fe818",
        "unrefreshed": [],
    },
}


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_every_written_spec_matches_the_pre_split_bytes(
    scenario: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    got = materialize(tmp_path, monkeypatch, scenario)
    expected = GOLDEN[scenario]
    digests = got.digests()
    assert sorted(digests["files"]) == sorted(expected["files"]), "a spec file appeared or vanished"
    # The goldens are CI's bytes: a developer host resolves different binaries and
    # gates, so they cannot be regenerated locally. A mismatch therefore prints
    # every digest this run produced, so one CI round is enough to re-pin a
    # deliberate change.
    regen = f"this run's digests for {scenario!r}:\n" + json.dumps(
        digests, indent=1, sort_keys=True
    )
    for name, digest in expected["files"].items():
        assert (
            digests["files"][name] == digest
        ), f"{scenario}: {name} no longer matches the pre-split bytes:\n{got.files[name]}\n{regen}"
    assert digests["events"] == expected["events"], (
        f"{scenario}: the audit record sequence changed:\n"
        + json.dumps(got.events, indent=1, sort_keys=True)
        + f"\n{regen}"
    )
    assert (
        digests["state"] == expected["state"]
    ), f"{scenario}: the agent-state sidecar changed:\n{got.state}\n{regen}"
    assert digests["unrefreshed"] == expected["unrefreshed"], "the fork refresh verdict changed"
