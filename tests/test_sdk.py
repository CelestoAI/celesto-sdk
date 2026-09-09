import httpx
import pytest

import celesto
from celesto import Computer
from celesto.sdk.client import _CelestoClient
from celesto.sdk.exceptions import CelestoServerError, CelestoValidationError


class DummySession:
    def __init__(self, *, status_code: int = 200, payload=None):
        self.status_code = status_code
        self.payload = payload if payload is not None else {}
        self.calls = []
        self.timeout = httpx.Timeout(connect=10, read=120, write=10, pool=10)

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        return httpx.Response(
            self.status_code,
            json=self.payload,
            request=httpx.Request(method, url),
        )

    def close(self):
        pass


def test_top_level_sdk_exports_new_computer_api_only():
    import celesto.sdk as public_sdk

    assert celesto.Computer is Computer
    assert public_sdk.Computer is Computer
    import celesto.sdk.client as internal_client

    assert not hasattr(celesto, "Celesto")
    assert not hasattr(public_sdk, "Celesto")
    assert not hasattr(internal_client, "Celesto")


def test_internal_client_still_supports_cli_service_operations():
    client = _CelestoClient("test-key", base_url="http://localhost:8500/v1")
    assert hasattr(client, "deployment")
    assert hasattr(client, "gatekeeper")
    assert hasattr(client, "computers")


def test_computer_convenience_api_creates_and_supports_mapping_access():
    session = DummySession(
        status_code=201,
        payload={
            "id": "cmp_1",
            "name": "curie",
            "status": "creating",
            "vcpus": 1,
            "ram_mb": 512,
            "disk_size_mb": 2048,
            "image": "ubuntu-desktop-24.04",
            "template_id": "scratch",
            "created_at": "2026-06-07T00:00:00Z",
        },
    )
    client = _CelestoClient("test-key", base_url="https://api.example.test/v1")
    client.session = session

    computer = Computer(
        cpus=1,
        memory=512,
        disk="2gb",
        persistent_home=True,
        client=client,
    )

    assert computer.name == "curie"
    assert computer["name"] == "curie"
    assert dict(computer)["id"] == "cmp_1"
    assert session.calls[0]["json"] == {
        "vcpus": 1,
        "ram_mb": 512,
        "disk_size_mb": 2048,
        "external_volume_enabled": True,
    }


def test_computer_convenience_api_runs_lifecycle_and_publishes_port():
    session = DummySession(
        status_code=201,
        payload={
            "id": "cmp_1",
            "name": "curie",
            "status": "running",
            "vcpus": 1,
            "ram_mb": 512,
            "disk_size_mb": 2048,
            "image": "ubuntu-desktop-24.04",
            "template_id": "scratch",
            "created_at": "2026-06-07T00:00:00Z",
        },
    )
    client = _CelestoClient("test-key", base_url="https://api.example.test/v1")
    client.session = session
    computer = Computer(client=client)

    session.payload = {"exit_code": 0, "stdout": "hello\n", "stderr": ""}
    result = computer.run("echo hello", timeout=60)

    assert result["stdout"] == "hello\n"
    assert session.calls[1]["url"] == "https://api.example.test/v1/computers/cmp_1/exec"
    assert session.calls[1]["json"] == {"command": "echo hello", "timeout": 60}

    session.payload = {
        "id": "cmp_1",
        "name": "curie",
        "status": "stopped",
        "vcpus": 1,
        "ram_mb": 512,
        "disk_size_mb": 2048,
        "image": "ubuntu-desktop-24.04",
        "template_id": "scratch",
        "created_at": "2026-06-07T00:00:00Z",
    }
    assert computer.stop().status == "stopped"

    session.payload = {
        "id": "cpp_123",
        "computer_id": "cmp_1",
        "port": 8080,
        "url": "https://p-test.celesto.ai",
        "status": "published",
        "created_at": "2026-06-07T00:00:00Z",
    }
    assert computer.publish_port(8080) == "https://p-test.celesto.ai"
    assert session.calls[-1]["url"] == (
        "https://api.example.test/v1/computers/cmp_1/published-ports"
    )


def test_computer_static_list_and_templates_do_not_require_public_client():
    session = DummySession(
        payload={
            "computers": [
                {
                    "id": "cmp_1",
                    "name": "curie",
                    "status": "running",
                    "vcpus": 1,
                    "ram_mb": 512,
                    "disk_size_mb": 2048,
                    "image": "ubuntu-desktop-24.04",
                    "template_id": "scratch",
                    "created_at": "2026-06-07T00:00:00Z",
                }
            ],
            "count": 1,
        },
    )
    client = _CelestoClient("test-key", base_url="https://api.example.test/v1")
    client.session = session

    computers = Computer.list(status="running", template_id="scratch", client=client)

    assert computers[0]["name"] == "curie"
    assert session.calls[0]["params"] == {
        "status": "running",
        "template_id": "scratch",
    }

    session.payload = [
        {
            "id": "scratch",
            "display_name": "Scratch",
            "description": "Minimal VM",
            "default_vcpus": 1,
            "default_ram_mb": 512,
            "default_disk_size_mb": 7168,
            "version": "latest",
            "experimental": False,
        }
    ]
    templates = Computer.list_templates(client=client)

    assert templates[0]["id"] == "scratch"
    assert session.calls[1]["url"] == "https://api.example.test/v1/computers/templates"


def test_computers_create_accepts_friendly_disk_alias():
    session = DummySession(status_code=201, payload={})
    client = _CelestoClient("test-key", base_url="https://api.example.test/v1")
    client.session = session

    client.computers.create(disk="1.5gb")

    assert session.calls[0]["json"] == {"disk_size_mb": 1536}


def test_computers_create_rejects_conflicting_disk_aliases():
    client = _CelestoClient("test-key", base_url="https://api.example.test/v1")

    with pytest.raises(CelestoValidationError):
        client.computers.create(disk="2gb", disk_size_mb=1024)


def test_computers_create_sends_only_explicit_overrides():
    session = DummySession(
        status_code=201,
        payload={
            "id": "cmp_1",
            "name": "curie",
            "status": "creating",
            "vcpus": 1,
            "ram_mb": 1024,
            "disk_size_mb": 15360,
            "image": "ubuntu-desktop-24.04",
            "template_id": "coding-agent",
            "template_version": "latest",
            "created_at": "2026-06-07T00:00:00Z",
        },
    )
    client = _CelestoClient("test-key", base_url="https://api.example.test/v1")
    client.session = session

    result = client.computers.create(
        template_id="coding-agent",
        disk_size_mb=15360,
        persistent_home=True,
    )

    assert result["template_id"] == "coding-agent"
    assert session.calls[0]["method"] == "POST"
    assert session.calls[0]["url"] == "https://api.example.test/v1/computers"
    assert session.calls[0]["json"] == {
        "disk_size_mb": 15360,
        "template_id": "coding-agent",
        "external_volume_enabled": True,
    }
    assert session.calls[0]["timeout"].read == 600
    assert session.timeout.read == 120


def test_computers_create_with_no_args_uses_backend_defaults():
    session = DummySession(status_code=201, payload={})
    client = _CelestoClient("test-key", base_url="https://api.example.test/v1")
    client.session = session

    client.computers.create()

    assert session.calls[0]["json"] == {}


def test_computers_create_can_explicitly_disable_persistent_home():
    session = DummySession(status_code=201, payload={})
    client = _CelestoClient("test-key", base_url="https://api.example.test/v1")
    client.session = session

    client.computers.create(persistent_home=False)

    assert session.calls[0]["json"] == {"external_volume_enabled": False}


def test_computers_create_rejects_conflicting_aliases():
    client = _CelestoClient("test-key", base_url="https://api.example.test/v1")

    with pytest.raises(CelestoValidationError):
        client.computers.create(cpus=1, vcpus=2)

    with pytest.raises(CelestoValidationError):
        client.computers.create(memory=1024, ram_mb=2048)


def test_computers_list_templates_hits_backend_endpoint():
    session = DummySession(
        payload=[
            {
                "id": "scratch",
                "display_name": "Scratch",
                "description": "Minimal VM",
                "default_vcpus": 1,
                "default_ram_mb": 512,
                "default_disk_size_mb": 7168,
                "version": "latest",
                "experimental": False,
            }
        ]
    )
    client = _CelestoClient("test-key", base_url="https://api.example.test/v1")
    client.session = session

    templates = client.computers.list_templates()

    assert templates[0]["id"] == "scratch"
    assert session.calls[0]["method"] == "GET"
    assert session.calls[0]["url"] == "https://api.example.test/v1/computers/templates"


def test_computers_list_preserves_default_unfiltered_request():
    session = DummySession(payload={"computers": [], "count": 0})
    client = _CelestoClient("test-key", base_url="https://api.example.test/v1")
    client.session = session

    result = client.computers.list()

    assert result["count"] == 0
    assert session.calls[0]["method"] == "GET"
    assert session.calls[0]["url"] == "https://api.example.test/v1/computers"
    assert session.calls[0]["params"] is None


def test_computers_list_sends_filters_as_query_params():
    session = DummySession(payload={"computers": [], "count": 0})
    client = _CelestoClient("test-key", base_url="https://api.example.test/v1")
    client.session = session

    client.computers.list(
        status="running",
        template_id="browser-agent",
        project_id="proj_123",
        limit=5,
    )

    assert session.calls[0]["params"] == {
        "status": "running",
        "template_id": "browser-agent",
        "project_id": "proj_123",
        "limit": 5,
    }


def test_computers_exec_uses_per_request_read_timeout_without_mutating_default():
    session = DummySession(payload={"exit_code": 0, "stdout": "ok\n", "stderr": ""})
    client = _CelestoClient("test-key", base_url="https://api.example.test/v1")
    client.session = session

    result = client.computers.exec("cmp_123", "sleep 1", timeout=60)

    assert result["stdout"] == "ok\n"
    assert (
        session.calls[0]["url"] == "https://api.example.test/v1/computers/cmp_123/exec"
    )
    assert session.calls[0]["json"] == {"command": "sleep 1", "timeout": 60}
    assert session.calls[0]["timeout"].read == 75
    assert session.timeout.read == 120


def test_computers_exec_aggregates_stream_for_long_timeouts(monkeypatch):
    session = DummySession(payload={"exit_code": 0, "stdout": "buffered\n"})
    client = _CelestoClient("test-key", base_url="https://api.example.test/v1")
    client.session = session
    stream_calls = []

    def fake_exec_stream(computer_id: str, command: str, *, timeout: int = 30):
        stream_calls.append((computer_id, command, timeout))
        yield {"type": "stdout", "data": "hello\n"}
        yield {"type": "stderr", "data": "warn\n"}
        yield {
            "type": "exit",
            "exit_code": "7",
            "duration_ms": 123,
            "timed_out": False,
            "command_id": "cmd_123",
        }

    monkeypatch.setattr(client.computers, "exec_stream", fake_exec_stream)

    result = client.computers.exec("cmp_123", "sleep 130", timeout=300)

    assert result == {
        "exit_code": 7,
        "stdout": "hello\n",
        "stderr": "warn\n",
        "command_id": "cmd_123",
        "duration_ms": 123,
        "timed_out": False,
    }
    assert stream_calls == [("cmp_123", "sleep 130", 300)]
    assert session.calls == []


def test_computer_creates_fast_terminal_gateway_session():
    session = DummySession(
        status_code=201,
        payload={
            "id": "cmp_1",
            "name": "curie",
            "status": "running",
            "vcpus": 1,
            "ram_mb": 512,
            "disk_size_mb": 2048,
            "image": "ubuntu-desktop-24.04",
            "template_id": "scratch",
            "created_at": "2026-06-07T00:00:00Z",
        },
    )
    client = _CelestoClient("test-key", base_url="https://api.example.test/v1")
    client.session = session
    computer = Computer(client=client)
    session.payload = {
        "terminal_id": "term_123",
        "gateway_url": "wss://gateway.example/v1/terminals/term_123/connect?region=us",
        "token": "short lived token",
        "expires_at": "2026-07-10T12:01:30Z",
    }

    result = computer.create_terminal_session()

    assert result["terminal_id"] == "term_123"
    assert result["url"] == (
        "wss://gateway.example/v1/terminals/term_123/connect"
        "?region=us&token=short+lived+token"
    )
    assert session.calls[1]["method"] == "POST"
    assert session.calls[1]["url"] == (
        "https://api.example.test/v1/computers/cmp_1/terminals"
    )


def test_terminal_session_rejects_incomplete_backend_response():
    session = DummySession(
        status_code=201,
        payload={
            "gateway_url": "wss://gateway.example/connect",
            "token": "short-lived-token",
        },
    )
    client = _CelestoClient("test-key", base_url="https://api.example.test/v1")
    client.session = session

    with pytest.raises(CelestoServerError, match="terminal connection details"):
        client.computers.create_terminal_session("cmp_123")


def test_computers_list_command_history_hits_backend_endpoint():
    session = DummySession(payload={"commands": []})
    client = _CelestoClient("test-key", base_url="https://api.example.test/v1")
    client.session = session

    result = client.computers.list_command_history("cmp_123", limit=10)

    assert result == {"commands": []}
    assert session.calls[0]["method"] == "GET"
    assert (
        session.calls[0]["url"]
        == "https://api.example.test/v1/computers/cmp_123/commands"
    )
    assert session.calls[0]["params"] == {"limit": 10}


def test_computers_publish_port_hits_backend_endpoint():
    session = DummySession(
        payload={
            "id": "cpp_123",
            "computer_id": "cmp_123",
            "port": 8000,
            "url": "https://p-test.celesto.ai",
            "status": "published",
            "created_at": "2026-06-07T00:00:00Z",
        }
    )
    client = _CelestoClient("test-key", base_url="https://api.example.test/v1")
    client.session = session

    result = client.computers.publish_port("curie", port=8000)

    assert result["url"] == "https://p-test.celesto.ai"
    assert session.calls[0]["method"] == "POST"
    assert (
        session.calls[0]["url"]
        == "https://api.example.test/v1/computers/curie/published-ports"
    )
    assert session.calls[0]["json"] == {"port": 8000}


def test_computers_list_published_ports_hits_backend_endpoint():
    session = DummySession(payload=[])
    client = _CelestoClient("test-key", base_url="https://api.example.test/v1")
    client.session = session

    result = client.computers.list_published_ports("cmp_123")

    assert result == []
    assert session.calls[0]["method"] == "GET"
    assert (
        session.calls[0]["url"]
        == "https://api.example.test/v1/computers/cmp_123/published-ports"
    )


def test_computers_unpublish_port_hits_backend_endpoint():
    session = DummySession(
        payload={
            "computer_id": "cmp_123",
            "port": 8000,
            "url": None,
            "status": "unpublished",
            "created_at": None,
        }
    )
    client = _CelestoClient("test-key", base_url="https://api.example.test/v1")
    client.session = session

    result = client.computers.unpublish_port("cmp_123", port=8000)

    assert result["status"] == "unpublished"
    assert session.calls[0]["method"] == "DELETE"
    assert (
        session.calls[0]["url"]
        == "https://api.example.test/v1/computers/cmp_123/published-ports/8000"
    )


class SequencedSession:
    """Session returning a queued payload per call, for multi-request flows."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.timeout = httpx.Timeout(connect=10, read=120, write=10, pool=10)

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        status_code, payload = self.responses.pop(0)
        return httpx.Response(
            status_code,
            json=payload,
            request=httpx.Request(method, url),
        )

    def close(self):
        pass


def _client_with(session):
    client = _CelestoClient("test-key", base_url="https://api.example.test/v1")
    client.session = session
    return client


def test_organizations_get_hits_backend_endpoint():
    session = DummySession(payload={"id": "org-1", "name": "Celesto prod"})
    client = _client_with(session)

    organization = client.organizations.get("org-1")

    assert organization["name"] == "Celesto prod"
    assert session.calls[0]["method"] == "GET"
    assert session.calls[0]["url"] == "https://api.example.test/v1/organizations/org-1"


def test_organizations_active_reads_bound_org_off_projects():
    session = SequencedSession(
        [
            (200, {"data": [{"id": "proj-1", "organization_id": "org-1"}]}),
            (200, {"id": "org-1", "name": "Celesto prod"}),
        ]
    )
    client = _client_with(session)

    assert client.organizations.active() == {"id": "org-1", "name": "Celesto prod"}

    projects_call = session.calls[0]
    assert projects_call["method"] == "GET"
    assert projects_call["url"] == "https://api.example.test/v1/projects/"
    assert projects_call["params"] == {"skip": 0, "limit": 1}
    assert session.calls[1]["url"] == "https://api.example.test/v1/organizations/org-1"


def test_organizations_active_returns_none_without_projects():
    session = SequencedSession([(200, {"data": []})])
    client = _client_with(session)

    assert client.organizations.active() is None
    # No organization to look up, so no second round trip.
    assert len(session.calls) == 1


def test_organizations_active_returns_none_when_project_has_no_org():
    session = SequencedSession([(200, {"data": [{"id": "proj-1"}]})])
    client = _client_with(session)

    assert client.organizations.active() is None
    assert len(session.calls) == 1


def test_organizations_active_returns_none_when_projects_request_fails():
    session = SequencedSession([(500, {"detail": "boom"})])
    client = _client_with(session)

    # Used only to label output, so a failed lookup must not raise.
    assert client.organizations.active() is None


def test_organizations_active_falls_back_to_id_when_lookup_fails():
    session = SequencedSession(
        [
            (200, {"data": [{"id": "proj-1", "organization_id": "org-1"}]}),
            (500, {"detail": "boom"}),
        ]
    )
    client = _client_with(session)

    assert client.organizations.active() == {"id": "org-1", "name": None}


@pytest.mark.parametrize("mode", ["open", "off"])
def test_computer_network_policy_reaches_api(mode):
    session = DummySession(payload={"id": "cmp_1", "network_policy": {"mode": mode}})
    client = _CelestoClient("test-key", base_url="https://api.example.test/v1")
    client.session = session
    computer = Computer(client=client, network_policy={"mode": mode})
    assert session.calls[0]["json"]["network_policy"] == {"mode": mode}
    assert computer.network_policy == {"mode": mode}


@pytest.mark.parametrize(
    "policy",
    [
        {"mode": "restricted"},
        {"mode": "off", "allowed_domains": ["example.com"]},
        "off",
    ],
)
def test_invalid_network_policy_does_not_send_request(policy):
    session = DummySession()
    client = _CelestoClient("test-key", base_url="https://api.example.test/v1")
    client.session = session
    with pytest.raises(CelestoValidationError, match="network_policy"):
        Computer(client=client, network_policy=policy)
    assert not session.calls


def test_offline_external_volume_does_not_send_request():
    session = DummySession()
    client = _CelestoClient("test-key", base_url="https://api.example.test/v1")
    client.session = session
    with pytest.raises(
        CelestoValidationError, match="External volumes require internet"
    ):
        Computer(client=client, network_policy={"mode": "off"}, persistent_home=True)
    assert not session.calls
