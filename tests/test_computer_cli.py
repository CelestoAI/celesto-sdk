from __future__ import annotations

import json
import os
from urllib.parse import urlparse

from typer.testing import CliRunner

from celesto import computer


def test_terminal_dimensions_return_rows_then_columns(monkeypatch):
    monkeypatch.setattr(
        computer.os,
        "get_terminal_size",
        lambda: os.terminal_size((120, 30)),
    )

    assert computer._terminal_dimensions() == (30, 120)


class _FakeComputers:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.exec_exit_code = 0
        self.stream_events = [
            {"stdout": "streamed\n"},
            {"exit_code": 0},
        ]

    def stop(self, computer_id: str) -> dict:
        self.calls.append(("stop", computer_id))
        return {"id": "cmp_123", "name": computer_id, "status": "stopping"}

    def delete(self, computer_id: str) -> dict:
        self.calls.append(("delete", computer_id))
        return {"id": "cmp_123", "name": computer_id, "status": "deleting"}

    @staticmethod
    def _computer_payload(name: str = "curie") -> dict:
        return {
            "id": "cmp_123",
            "name": name,
            "status": "running",
            "vcpus": 1,
            "ram_mb": 1024,
            "disk_size_mb": 7168,
            "image": "ubuntu-desktop-24.04",
            "template_id": "scratch",
            "created_at": "2026-06-07T00:00:00Z",
        }

    def create(self, **kwargs) -> dict:
        self.calls.append(("create", kwargs))
        return self._computer_payload()

    def list(
        self,
        *,
        status: str | None = None,
        template_id: str | None = None,
        project_id: str | None = None,
        limit: int | None = None,
    ) -> dict:
        self.calls.append(("list", status, template_id, project_id, limit))
        return {"computers": [self._computer_payload()], "count": 1}

    def get(self, computer_id: str) -> dict:
        self.calls.append(("get", computer_id))
        return self._computer_payload(name=computer_id)

    def exec(self, computer_id: str, command: str, *, timeout: int = 30) -> dict:
        self.calls.append(("exec", computer_id, command, timeout))
        return {
            "exit_code": self.exec_exit_code,
            "stdout": "ok\n",
            "stderr": "",
        }

    def exec_stream(self, computer_id: str, command: str, *, timeout: int = 30):
        self.calls.append(("exec_stream", computer_id, command, timeout))
        yield from self.stream_events

    def create_terminal_session(self, computer_id: str) -> dict:
        self.calls.append(("terminal", computer_id))
        return {
            "terminal_id": "term_123",
            "gateway_url": "wss://gateway.example/v1/terminals/term_123/connect",
            "token": "short-lived-token",
            "expires_at": "2026-07-10T12:01:30Z",
            "url": "wss://gateway.example/v1/terminals/term_123/connect?token=short-lived-token",
        }

    def publish_port(self, computer_id: str, *, port: int = 8000) -> dict:
        self.calls.append(("publish", computer_id, port))
        return {
            "id": "cpp_123",
            "computer_id": "cmp_123",
            "port": port,
            "url": "https://p-test.celesto.ai",
            "status": "published",
            "created_at": "2026-06-07T00:00:00Z",
        }

    def list_published_ports(self, computer_id: str) -> list[dict]:
        self.calls.append(("list", computer_id, None))
        return [
            {
                "id": "cpp_123",
                "computer_id": "cmp_123",
                "port": 8000,
                "url": "https://p-test.celesto.ai",
                "status": "published",
                "created_at": "2026-06-07T00:00:00Z",
            }
        ]

    def unpublish_port(self, computer_id: str, *, port: int = 8000) -> dict:
        self.calls.append(("unpublish", computer_id, port))
        return {
            "computer_id": "cmp_123",
            "port": port,
            "url": None,
            "status": "unpublished",
            "created_at": None,
        }


class _FakeOrganizations:
    def __init__(self, organization: dict[str, str] | None = None) -> None:
        self.organization = organization
        self.calls: list[str] = []

    def active(self) -> dict[str, str] | None:
        self.calls.append("active")
        return self.organization


_DEFAULT_ORGANIZATION = {"id": "org-prod", "name": "Celesto prod"}


class _FakeClient:
    def __init__(self, organization: dict[str, str] | None = _DEFAULT_ORGANIZATION):
        self.computers = _FakeComputers()
        self.organizations = _FakeOrganizations(organization)

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def test_terminal_gateway_error_frames_are_detected():
    assert computer._is_terminal_gateway_error(
        '{"type":"error","message":"host unavailable"}'
    )
    assert not computer._is_terminal_gateway_error("shell output")


def test_closing_terminal_session_stops_remote_shell():
    class FakeWebSocket:
        def __init__(self) -> None:
            self.sent: list[str] = []
            self.closed = False

        def send(self, message: str) -> None:
            self.sent.append(message)

        def close(self) -> None:
            self.closed = True

    ws = FakeWebSocket()

    computer._close_terminal_session(ws)

    assert [json.loads(message) for message in ws.sent] == [{"type": "close"}]
    assert ws.closed


def test_terminal_session_uses_resolved_computer_and_fast_gateway():
    fake_client = _FakeClient()

    result = computer._create_terminal_session_with_resume(fake_client, "curie")

    assert result["url"].startswith("wss://gateway.example/")
    assert fake_client.computers.calls == [
        ("get", "curie"),
        ("terminal", "cmp_123"),
    ]


def test_computer_port_publish_prints_url(monkeypatch):
    runner = CliRunner()
    fake_client = _FakeClient()
    monkeypatch.setattr(computer, "_get_client", lambda api_key=None: fake_client)

    result = runner.invoke(computer.app, ["port", "publish", "curie"])

    assert result.exit_code == 0
    urls = []
    for token in result.output.split():
        parsed = urlparse(token)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            urls.append(parsed)
    assert any(u.scheme == "https" and u.hostname == "p-test.celesto.ai" for u in urls)
    assert fake_client.computers.calls == [("publish", "curie", 8000)]


def test_computer_create_enables_persistent_home(monkeypatch):
    runner = CliRunner()
    fake_client = _FakeClient()
    monkeypatch.setattr(computer, "_get_client", lambda api_key=None: fake_client)

    result = runner.invoke(
        computer.app,
        ["create", "--persistent-home", "--json"],
    )

    assert result.exit_code == 0
    assert fake_client.computers.calls == [
        (
            "create",
            {
                "cpus": None,
                "memory": None,
                "disk_size_mb": None,
                "template_id": None,
                "template_version": None,
                "image": None,
                "persistent_home": True,
            },
        )
    ]


def test_computer_get_json(monkeypatch):
    runner = CliRunner()
    fake_client = _FakeClient()
    monkeypatch.setattr(computer, "_get_client", lambda api_key=None: fake_client)

    result = runner.invoke(computer.app, ["get", "curie", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["id"] == "cmp_123"
    assert payload["name"] == "curie"
    assert fake_client.computers.calls == [("get", "curie")]


def test_computer_list_passes_filters_to_sdk(monkeypatch):
    runner = CliRunner()
    fake_client = _FakeClient()
    monkeypatch.setattr(computer, "_get_client", lambda api_key=None: fake_client)

    result = runner.invoke(
        computer.app,
        [
            "list",
            "--status",
            "running",
            "--template",
            "browser-agent",
            "--project",
            "proj_123",
            "--limit",
            "5",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload[0]["name"] == "curie"
    assert fake_client.computers.calls == [
        ("list", "running", "browser-agent", "proj_123", 5)
    ]


def test_computer_run_json_exits_with_remote_exit_code(monkeypatch):
    runner = CliRunner()
    fake_client = _FakeClient()
    fake_client.computers.exec_exit_code = 7
    monkeypatch.setattr(computer, "_get_client", lambda api_key=None: fake_client)

    result = runner.invoke(computer.app, ["run", "curie", "false", "--json"])

    assert result.exit_code == 7
    payload = json.loads(result.output)
    assert payload["exit_code"] == 7
    assert fake_client.computers.calls == [("exec", "curie", "false", 30)]


def test_computer_run_stream_invokes_sdk_method_and_prints_output(monkeypatch):
    runner = CliRunner()
    fake_client = _FakeClient()
    monkeypatch.setattr(computer, "_get_client", lambda api_key=None: fake_client)

    result = runner.invoke(
        computer.app,
        ["run", "curie", "printf hello", "--stream", "--timeout", "45"],
    )

    assert result.exit_code == 0
    assert "streamed\n" in result.output
    assert fake_client.computers.calls == [("exec_stream", "curie", "printf hello", 45)]


def test_computer_run_stream_routes_stderr_events_to_stderr(monkeypatch):
    runner = CliRunner()
    fake_client = _FakeClient()
    fake_client.computers.stream_events = [
        {"type": "stderr", "data": "warn\n"},
        {"type": "exit", "exit_code": 0},
    ]
    monkeypatch.setattr(computer, "_get_client", lambda api_key=None: fake_client)

    result = runner.invoke(computer.app, ["run", "curie", "warn", "--stream"])

    assert result.exit_code == 0
    assert result.stdout == ""
    assert result.stderr == "warn\n"


def test_computer_run_stream_fails_when_exit_event_is_missing(monkeypatch):
    runner = CliRunner()
    fake_client = _FakeClient()
    fake_client.computers.stream_events = [{"type": "stdout", "data": "partial\n"}]
    monkeypatch.setattr(computer, "_get_client", lambda api_key=None: fake_client)

    result = runner.invoke(computer.app, ["run", "curie", "partial", "--stream"])

    assert result.exit_code == 1
    assert result.stdout == "partial\n"
    assert "ended before the remote exit status" in result.stderr


def test_computer_run_rejects_timeout_outside_allowed_range(monkeypatch):
    runner = CliRunner()
    fake_client = _FakeClient()
    monkeypatch.setattr(computer, "_get_client", lambda api_key=None: fake_client)

    result = runner.invoke(computer.app, ["run", "curie", "echo ok", "--timeout", "0"])

    assert result.exit_code != 0
    assert fake_client.computers.calls == []


def test_computer_port_publish_json(monkeypatch):
    runner = CliRunner()
    fake_client = _FakeClient()
    monkeypatch.setattr(computer, "_get_client", lambda api_key=None: fake_client)

    result = runner.invoke(computer.app, ["port", "publish", "cmp_123", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["url"] == "https://p-test.celesto.ai"
    assert fake_client.computers.calls == [("publish", "cmp_123", 8000)]


def test_computer_port_list_json(monkeypatch):
    runner = CliRunner()
    fake_client = _FakeClient()
    monkeypatch.setattr(computer, "_get_client", lambda api_key=None: fake_client)

    result = runner.invoke(computer.app, ["port", "list", "cmp_123", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload[0]["port"] == 8000
    assert fake_client.computers.calls == [("list", "cmp_123", None)]


def test_computer_port_unpublish_json(monkeypatch):
    runner = CliRunner()
    fake_client = _FakeClient()
    monkeypatch.setattr(computer, "_get_client", lambda api_key=None: fake_client)

    result = runner.invoke(computer.app, ["port", "unpublish", "cmp_123", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["status"] == "unpublished"
    assert fake_client.computers.calls == [("unpublish", "cmp_123", 8000)]


# --- Destructive commands name the target organization ---------------------
#
# An API key is bound to one organization, and a .env in the working directory
# can silently change which one. Deleting is irreversible, so the confirmation
# has to say which tenant is about to lose the computer.


def test_delete_confirmation_names_the_target_organization(monkeypatch):
    runner = CliRunner()
    fake_client = _FakeClient({"id": "org-prod", "name": "Celesto prod"})
    monkeypatch.setattr(computer, "_get_client", lambda api_key=None: fake_client)

    result = runner.invoke(computer.app, ["delete", "curie"], input="y\n")

    assert result.exit_code == 0
    assert "Celesto prod (org-prod)" in result.output
    assert fake_client.organizations.calls == ["active"]
    assert ("delete", "curie") in fake_client.computers.calls


def test_delete_aborts_without_calling_the_api(monkeypatch):
    runner = CliRunner()
    fake_client = _FakeClient()
    monkeypatch.setattr(computer, "_get_client", lambda api_key=None: fake_client)

    result = runner.invoke(computer.app, ["delete", "curie"], input="n\n")

    assert result.exit_code != 0
    assert ("delete", "curie") not in fake_client.computers.calls


def test_delete_force_skips_prompt_and_org_lookup(monkeypatch):
    runner = CliRunner()
    fake_client = _FakeClient()
    monkeypatch.setattr(computer, "_get_client", lambda api_key=None: fake_client)

    result = runner.invoke(computer.app, ["delete", "curie", "--force"])

    assert result.exit_code == 0
    # --force is the scripted path: it must not pay for an extra API round trip.
    assert fake_client.organizations.calls == []
    assert ("delete", "curie") in fake_client.computers.calls


def test_stop_names_the_target_organization(monkeypatch):
    runner = CliRunner()
    fake_client = _FakeClient({"id": "org-prod", "name": "Celesto prod"})
    monkeypatch.setattr(computer, "_get_client", lambda api_key=None: fake_client)

    result = runner.invoke(computer.app, ["stop", "curie"])

    assert result.exit_code == 0
    assert "Celesto prod (org-prod)" in result.output


def test_stop_json_output_stays_clean(monkeypatch):
    runner = CliRunner()
    fake_client = _FakeClient()
    monkeypatch.setattr(computer, "_get_client", lambda api_key=None: fake_client)

    result = runner.invoke(computer.app, ["stop", "curie", "--json"])

    assert result.exit_code == 0
    json.loads(result.output)
    assert fake_client.organizations.calls == []


def test_stop_falls_back_when_organization_is_unknown(monkeypatch):
    runner = CliRunner()
    fake_client = _FakeClient(organization=None)
    monkeypatch.setattr(computer, "_get_client", lambda api_key=None: fake_client)

    result = runner.invoke(computer.app, ["stop", "curie"])

    assert result.exit_code == 0
    assert "Computer curie is being stopped." in result.output


def test_delete_prompt_omits_organization_when_unknown(monkeypatch):
    runner = CliRunner()
    fake_client = _FakeClient(organization=None)
    monkeypatch.setattr(computer, "_get_client", lambda api_key=None: fake_client)

    result = runner.invoke(computer.app, ["delete", "curie"], input="y\n")

    assert result.exit_code == 0
    # Never name an organization we could not actually determine.
    assert "unknown" not in result.output
    assert "Delete computer curie?" in result.output


def test_computer_create_without_internet(monkeypatch):
    fake_client = _FakeClient()
    monkeypatch.setattr(computer, "_get_client", lambda api_key=None: fake_client)
    result = CliRunner().invoke(computer.app, ["create", "--no-internet", "--json"])
    assert result.exit_code == 0
    assert fake_client.computers.calls[0][1]["network_policy"] == {"mode": "off"}
