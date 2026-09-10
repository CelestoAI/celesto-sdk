from __future__ import annotations

import ast
import py_compile
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
OPENAI_AGENTS_DIR = REPO_ROOT / "src" / "celesto" / "integrations" / "openai_agents"


def test_openai_agents_integration_compiles_without_optional_dependencies() -> None:
    """The optional integration should parse even when extras are not installed."""
    for name in ["common.py", "hosted.py", "smolvm.py", "__init__.py"]:
        py_compile.compile(str(OPENAI_AGENTS_DIR / name), doraise=True)


def test_hosted_integration_carries_network_policy_through_session_state() -> None:
    """Keep network controls wired even when the optional extra is absent."""
    module = ast.parse((OPENAI_AGENTS_DIR / "hosted.py").read_text())
    classes = {
        node.name: node
        for node in module.body
        if isinstance(node, ast.ClassDef)
    }

    for class_name in ["CelestoSandboxClientOptions", "CelestoSandboxSessionState"]:
        fields = {
            node.target.id
            for node in classes[class_name].body
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        }
        assert "network_policy" in fields

    source = ast.unparse(module)
    assert "network_policy=self.state.network_policy" in source
    assert "network_policy=resolved.network_policy" in source
    assert "info.get('network_policy') != self.state.network_policy" in source


def test_hosted_options_round_trip_network_policy_when_extra_is_installed() -> None:
    """Exercise the typed options model in environments that install the extra."""
    pytest.importorskip("agents")
    from celesto.integrations.openai_agents.hosted import CelestoSandboxClientOptions

    options = CelestoSandboxClientOptions(network_policy={"mode": "off"})

    assert options.network_policy == {"mode": "off"}
    assert options.model_dump()["network_policy"] == {"mode": "off"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("requested_policy", "responses", "raises", "expected_starts"),
    [
        (None, [{"status": "running", "network_policy": {"mode": "open"}}], False, 0),
        (
            {"mode": "off"},
            [
                {"status": "stopped", "network_policy": {"mode": "off"}},
                {"status": "running", "network_policy": {"mode": "off"}},
            ],
            False,
            1,
        ),
        (
            {"mode": "off"},
            [{"status": "running", "network_policy": {"mode": "open"}}],
            True,
            0,
        ),
    ],
)
async def test_existing_hosted_computer_enforces_requested_network_policy(
    requested_policy, responses, raises, expected_starts
) -> None:
    """Run every existing-computer policy branch when the extra is installed."""
    pytest.importorskip("agents")
    from celesto.integrations.openai_agents.hosted import (
        CelestoSandboxSession,
        CelestoSandboxSessionState,
        Manifest,
        resolve_snapshot,
    )

    class FakeComputers:
        def __init__(self) -> None:
            self.responses = list(responses)
            self.starts = []

        def get(self, computer_id):
            assert computer_id == "cmp_existing"
            return self.responses.pop(0)

        def start(self, computer_id):
            self.starts.append(computer_id)

    session_id = uuid.uuid4()
    computers = FakeComputers()
    state = CelestoSandboxSessionState(
        session_id=session_id,
        manifest=Manifest(),
        snapshot=resolve_snapshot(None, str(session_id)),
        computer_id="cmp_existing",
        network_policy=requested_policy,
        start_poll_interval_seconds=0.01,
    )
    session = CelestoSandboxSession(
        state=state,
        client=SimpleNamespace(computers=computers),
    )

    if raises:
        with pytest.raises(RuntimeError, match="does not match the requested"):
            await session._ensure_backend_started()
    else:
        await session._ensure_backend_started()

    assert computers.starts == ["cmp_existing"] * expected_starts


@pytest.mark.asyncio
async def test_new_hosted_computer_forwards_requested_network_policy() -> None:
    """Exercise the real session-to-client call when the extra is installed."""
    pytest.importorskip("agents")
    from celesto.integrations.openai_agents.hosted import (
        CelestoSandboxSession,
        CelestoSandboxSessionState,
        Manifest,
        resolve_snapshot,
    )

    class FakeComputers:
        def __init__(self) -> None:
            self.create_kwargs = None

        def create(self, **kwargs):
            self.create_kwargs = kwargs
            return {"id": "cmp_created", "status": "running"}

    session_id = uuid.uuid4()
    computers = FakeComputers()
    state = CelestoSandboxSessionState(
        session_id=session_id,
        manifest=Manifest(),
        snapshot=resolve_snapshot(None, str(session_id)),
        network_policy={"mode": "off"},
    )
    session = CelestoSandboxSession(
        state=state,
        client=SimpleNamespace(computers=computers),
    )

    await session._ensure_backend_started()

    assert computers.create_kwargs["network_policy"] == {"mode": "off"}
    assert state.computer_id == "cmp_created"
