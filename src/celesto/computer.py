"""CLI commands for managing sandboxed computers."""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Iterable
from typing import Any, Optional

import typer
from rich.console import Console
from rich.table import Table
from typing_extensions import Annotated

from .auth import describe_organization
from .deployment import _get_api_key
from .sdk.client import _CelestoClient
from .sdk.exceptions import CelestoServerError

app = typer.Typer(help="Create, manage, and connect to sandboxed computers.")
port_app = typer.Typer(help="Publish and unpublish computer ports.")
app.add_typer(port_app, name="port")
console = Console()

# Common option types
ApiKeyOption = Annotated[
    Optional[str],
    typer.Option("--api-key", "-k", help="Celesto API key"),
]
JsonOption = Annotated[
    bool,
    typer.Option("--json", "-j", help="Output as JSON (for machines and AI agents)"),
]


def _terminal_dimensions() -> tuple[int, int]:
    """Return terminal size as rows, columns."""
    size = os.get_terminal_size()
    return size.lines, size.columns


def _get_client(api_key: str | None = None) -> _CelestoClient:
    """Create SDK client with resolved API key."""
    key = _get_api_key(api_key)
    return _CelestoClient(api_key=key)


def _status_color(status: str) -> str:
    colors = {
        "creating": "yellow",
        "running": "green",
        "stopping": "yellow",
        "stopped": "dim",
        "starting": "yellow",
        "restoring": "yellow",
        "restorable": "cyan",
        "deleting": "yellow",
        "deleted": "dim",
        "error": "red",
    }
    return colors.get(status, "white")


def _format_memory(mb: int) -> str:
    if mb >= 1024:
        return f"{mb / 1024:.0f} GB"
    return f"{mb} MB"


def _format_optional_memory(value: object) -> str:
    if isinstance(value, int):
        return _format_memory(value)
    return "N/A"


def _format_optional_text(value: object) -> str:
    if isinstance(value, str) and value:
        return value
    return "N/A"


def _print_json(data: object) -> None:
    """Print JSON to stdout (no Rich formatting)."""
    sys.stdout.write(json.dumps(data, indent=2, default=str) + "\n")


def _print_json_line(data: object) -> None:
    """Print one compact JSON event for streaming output."""
    sys.stdout.write(json.dumps(data, default=str) + "\n")


def _coerce_exit_code(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.lstrip("-").isdigit():
        return int(value)
    return 0


def _print_computer_details(info: dict[str, Any]) -> None:
    name = info.get("name", "")
    status = str(info.get("status", ""))
    color = _status_color(status)

    console.print(f"  Name:   [bold]{name}[/bold]")
    console.print(f"  ID:     [dim]{info.get('id', '')}[/dim]")
    console.print(f"  Status: [{color}]{status}[/{color}]")
    console.print(f"  CPUs:   {info.get('vcpus', 'N/A')}")
    console.print(f"  Memory: {_format_optional_memory(info.get('ram_mb'))}")
    console.print(f"  Disk:   {_format_optional_memory(info.get('disk_size_mb'))}")
    console.print(f"  Template: {_format_optional_text(info.get('template_id'))}")
    if info.get("created_at"):
        console.print(f"  Created: {str(info.get('created_at'))[:19]}")


def _is_stopped_conflict(error: CelestoServerError) -> bool:
    message = str(error).lower()
    return "stopped" in message or "409" in message


def _resume_computer(
    client: _CelestoClient, computer_id: str, *, quiet: bool = False
) -> None:
    if not quiet:
        console.print("[yellow]Computer is stopped. Resuming...[/yellow]")
    client.computers.start(computer_id)
    for _ in range(30):
        info = client.computers.get(computer_id)
        if info.get("status") == "running":
            break
        time.sleep(1)
    else:
        if not quiet:
            console.print("[red]Computer failed to resume.[/red]")
        raise typer.Exit(1)
    if not quiet:
        console.print("[green]Computer resumed.[/green]")


def _exec_with_resume(
    client: _CelestoClient,
    computer_id: str,
    command: str,
    *,
    timeout: int,
    quiet: bool = False,
) -> dict[str, Any]:
    try:
        return client.computers.exec(computer_id, command, timeout=timeout)
    except CelestoServerError as e:
        if not _is_stopped_conflict(e):
            raise
        _resume_computer(client, computer_id, quiet=quiet)
        return client.computers.exec(computer_id, command, timeout=timeout)


def _exec_stream_with_resume(
    client: _CelestoClient,
    computer_id: str,
    command: str,
    *,
    timeout: int,
    quiet: bool = False,
) -> Iterable[dict[str, Any]]:
    try:
        yield from client.computers.exec_stream(computer_id, command, timeout=timeout)
    except CelestoServerError as e:
        if not _is_stopped_conflict(e):
            raise
        _resume_computer(client, computer_id, quiet=quiet)
        yield from client.computers.exec_stream(computer_id, command, timeout=timeout)


def _create_terminal_session_with_resume(
    client: _CelestoClient,
    computer_id: str,
) -> dict[str, Any]:
    """Resolve, resume, and create a fast terminal gateway session."""
    info = client.computers.get(computer_id)
    resolved_id = str(info.get("id") or computer_id)
    if info.get("status") == "stopped":
        _resume_computer(client, resolved_id)
    return client.computers.create_terminal_session(resolved_id)


def _is_terminal_gateway_error(message: str) -> bool:
    """Return whether a terminal gateway text frame reports an error."""
    try:
        payload = json.loads(message)
    except (json.JSONDecodeError, TypeError):
        return False
    return isinstance(payload, dict) and payload.get("type") == "error"


def _close_terminal_session(ws: Any) -> None:
    """Close the remote shell before disconnecting its WebSocket."""
    try:
        ws.send(json.dumps({"type": "close"}))
    except Exception:
        pass
    try:
        ws.close()
    except Exception:
        pass


def _write_stream_event(event: dict[str, Any], *, as_json: bool = False) -> int | None:
    if as_json:
        _print_json_line(event)
    else:
        wrote = False
        stdout = event.get("stdout")
        stderr = event.get("stderr")
        if stdout is not None:
            sys.stdout.write(str(stdout))
            sys.stdout.flush()
            wrote = True
        if stderr is not None:
            sys.stderr.write(str(stderr))
            sys.stderr.flush()
            wrote = True
        if not wrote and "data" in event:
            destination = (
                sys.stderr
                if event.get("stream") == "stderr" or event.get("type") == "stderr"
                else sys.stdout
            )
            destination.write(str(event["data"]))
            destination.flush()

    if "exit_code" in event:
        return _coerce_exit_code(event.get("exit_code"))
    return None


@port_app.command("publish")
def publish_port(
    computer_id: Annotated[str, typer.Argument(help="Computer ID or name")],
    port: Annotated[
        int,
        typer.Option("--port", "-p", help="Application port to publish (1024-65535)"),
    ] = 8000,
    as_json: JsonOption = False,
    api_key: ApiKeyOption = None,
):
    """Publish a computer port to the internet."""
    with _get_client(api_key) as client:
        result = client.computers.publish_port(computer_id, port=port)

    if as_json:
        _print_json(result)
        return

    console.print(result.get("url") or "")


@port_app.command("list")
def list_ports(
    computer_id: Annotated[str, typer.Argument(help="Computer ID or name")],
    as_json: JsonOption = False,
    api_key: ApiKeyOption = None,
):
    """List published ports for a computer."""
    with _get_client(api_key) as client:
        ports = client.computers.list_published_ports(computer_id)

    if as_json:
        _print_json(ports)
        return

    if not ports:
        console.print("[dim]No published ports.[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Port", justify="right")
    table.add_column("Status")
    table.add_column("URL")
    table.add_column("Created")

    for published_port in ports:
        table.add_row(
            str(published_port.get("port", "")),
            str(published_port.get("status", "")),
            str(published_port.get("url") or ""),
            str(published_port.get("created_at") or "")[:19],
        )

    console.print(table)


@port_app.command("unpublish")
def unpublish_port(
    computer_id: Annotated[str, typer.Argument(help="Computer ID or name")],
    port: Annotated[
        int,
        typer.Option("--port", "-p", help="Application port to unpublish (1024-65535)"),
    ] = 8000,
    as_json: JsonOption = False,
    api_key: ApiKeyOption = None,
):
    """Unpublish a computer port."""
    with _get_client(api_key) as client:
        result = client.computers.unpublish_port(computer_id, port=port)

    if as_json:
        _print_json(result)
        return

    console.print(f"[dim]Port {port} is unpublished.[/dim]")


@app.command("create")
def create_computer(
    cpus: Annotated[
        Optional[int], typer.Option("--cpus", "-c", help="Number of virtual CPUs")
    ] = None,
    memory: Annotated[
        Optional[int], typer.Option("--memory", "-m", help="Memory in MB")
    ] = None,
    disk_size_mb: Annotated[
        Optional[int],
        typer.Option("--disk-size-mb", "--disk", help="Disk size in MB"),
    ] = None,
    template_id: Annotated[
        Optional[str],
        typer.Option(
            "--template",
            "--template-id",
            help="Sandbox template id, such as scratch, coding-agent, or browser-agent",
        ),
    ] = None,
    template_version: Annotated[
        Optional[str],
        typer.Option("--template-version", help="Immutable template version"),
    ] = None,
    image: Annotated[
        Optional[str],
        typer.Option("--image", help="Legacy image selector"),
    ] = None,
    internet: Annotated[
        bool,
        typer.Option(
            "--internet/--no-internet",
            help="Allow outbound internet access; fixed at creation.",
        ),
    ] = True,
    persistent_home: Annotated[
        bool,
        typer.Option(
            "--persistent-home",
            help="Keep /home/ohm across stop and restore; cannot be changed later",
        ),
    ] = False,
    as_json: JsonOption = False,
    api_key: ApiKeyOption = None,
):
    """Create a new sandboxed computer."""
    with _get_client(api_key) as client:
        if not as_json:
            console.print("Creating computer...", style="dim")
        result = client.computers.create(
            cpus=cpus,
            memory=memory,
            disk_size_mb=disk_size_mb,
            template_id=template_id,
            template_version=template_version,
            image=image,
            persistent_home=persistent_home,
            **({"network_policy": {"mode": "off"}} if not internet else {}),
        )

    if as_json:
        _print_json(result)
        return

    cname = result.get("name", "")
    cid = result["id"]
    status = result["status"]
    color = _status_color(status)

    console.print(f"  Name:   [bold]{cname}[/bold]")
    console.print(f"  ID:     [dim]{cid}[/dim]")
    console.print(f"  Status: [{color}]{status}[/{color}]")
    console.print(f"  CPUs:   {result.get('vcpus')}")
    console.print(f"  Memory: {_format_optional_memory(result.get('ram_mb'))}")
    console.print(f"  Disk:   {_format_optional_memory(result.get('disk_size_mb'))}")
    console.print(f"  Template: {_format_optional_text(result.get('template_id'))}")
    console.print()
    console.print(f"[dim]Connect with:[/dim] celesto computer ssh {cname}")


@app.command("get")
def get_computer(
    computer_id: Annotated[str, typer.Argument(help="Computer ID or name")],
    as_json: JsonOption = False,
    api_key: ApiKeyOption = None,
):
    """Get one computer by name or ID."""
    with _get_client(api_key) as client:
        result = client.computers.get(computer_id)

    if as_json:
        _print_json(result)
        return

    _print_computer_details(result)


@app.command("list")
def list_computers(
    status: Annotated[
        Optional[str], typer.Option("--status", help="Filter by computer status")
    ] = None,
    template_id: Annotated[
        Optional[str],
        typer.Option("--template", "--template-id", help="Filter by template ID"),
    ] = None,
    project_id: Annotated[
        Optional[str],
        typer.Option("--project", "--project-id", help="Filter by project ID"),
    ] = None,
    limit: Annotated[
        Optional[int], typer.Option("--limit", min=1, help="Maximum computers to list")
    ] = None,
    as_json: JsonOption = False,
    api_key: ApiKeyOption = None,
):
    """List all computers."""
    with _get_client(api_key) as client:
        result = client.computers.list(
            status=status,
            template_id=template_id,
            project_id=project_id,
            limit=limit,
        )

    computers = result.get("computers", [])

    if as_json:
        _print_json(computers)
        return

    if not computers:
        console.print("[dim]No computers found. Create one with:[/dim]")
        console.print("  celesto computer create")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Name", style="bold")
    table.add_column("ID", style="dim")
    table.add_column("Status")
    table.add_column("CPUs", justify="right")
    table.add_column("Memory", justify="right")
    table.add_column("Disk", justify="right")
    table.add_column("Template")
    table.add_column("Created")

    for c in computers:
        color = _status_color(c["status"])
        table.add_row(
            c.get("name", ""),
            c["id"],
            f"[{color}]{c['status']}[/{color}]",
            str(c["vcpus"]),
            _format_memory(c["ram_mb"]),
            _format_optional_memory(c.get("disk_size_mb")),
            _format_optional_text(c.get("template_id")),
            c.get("created_at", "")[:19],
        )

    console.print(table)


@app.command("templates")
def list_templates(
    as_json: JsonOption = False,
    api_key: ApiKeyOption = None,
):
    """List ready-made computer setups."""
    with _get_client(api_key) as client:
        templates = client.computers.list_templates()

    if as_json:
        _print_json(templates)
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("ID", style="bold")
    table.add_column("Name")
    table.add_column("CPUs", justify="right")
    table.add_column("Memory", justify="right")
    table.add_column("Disk", justify="right")
    table.add_column("Version")
    table.add_column("Experimental")

    for template in templates:
        table.add_row(
            template["id"],
            template["display_name"],
            str(template["default_vcpus"]),
            _format_memory(template["default_ram_mb"]),
            _format_memory(template["default_disk_size_mb"]),
            template.get("version") or "",
            "yes" if template.get("experimental") else "",
        )

    console.print(table)


@app.command("run")
def run_command(
    computer_id: Annotated[str, typer.Argument(help="Computer ID or name")],
    command: Annotated[str, typer.Argument(help="Command to execute")],
    timeout: Annotated[
        int,
        typer.Option("--timeout", "-t", min=1, max=300, help="Timeout in seconds"),
    ] = 30,
    stream: Annotated[
        bool, typer.Option("--stream", help="Stream output while the command runs")
    ] = False,
    as_json: JsonOption = False,
    api_key: ApiKeyOption = None,
):
    """Execute a command on a computer. Automatically resumes stopped computers."""
    with _get_client(api_key) as client:
        if stream:
            exit_code = 0
            saw_exit = False
            events = _exec_stream_with_resume(
                client,
                computer_id,
                command,
                timeout=timeout,
                quiet=as_json,
            )
            for event in events:
                event_exit_code = _write_stream_event(event, as_json=as_json)
                if event_exit_code is not None:
                    exit_code = event_exit_code
                    saw_exit = True
            if not saw_exit:
                message = (
                    "Command stream ended before the remote exit status was received."
                )
                if as_json:
                    _print_json_line({"type": "error", "data": message})
                else:
                    sys.stderr.write(f"{message}\n")
                    sys.stderr.flush()
                exit_code = 1
            raise typer.Exit(exit_code)

        result = _exec_with_resume(
            client,
            computer_id,
            command,
            timeout=timeout,
            quiet=as_json,
        )

    if as_json:
        _print_json(result)
        raise typer.Exit(_coerce_exit_code(result.get("exit_code")))

    if result.get("stdout"):
        sys.stdout.write(result["stdout"])
    if result.get("stderr"):
        sys.stderr.write(result["stderr"])

    raise typer.Exit(result.get("exit_code", 0))


@app.command("ssh")
def ssh_to_computer(
    computer_id: Annotated[str, typer.Argument(help="Computer ID or name")],
    api_key: ApiKeyOption = None,
):
    """Open an interactive terminal session on a computer. Automatically resumes stopped computers."""
    import select
    import signal
    import termios
    import threading
    import tty

    import websockets.sync.client

    with _get_client(api_key) as client:
        terminal_session = _create_terminal_session_with_resume(client, computer_id)

    ws_url = terminal_session.get("url")
    if not isinstance(ws_url, str) or not ws_url:
        console.print(
            f"[red]Celesto did not return a terminal connection for {computer_id}. Run `celesto computer ssh {computer_id}` again.[/red]"
        )
        raise typer.Exit(1)

    console.print(f"[dim]Connecting to {computer_id}...[/dim]")

    ws = None
    try:
        ws = websockets.sync.client.connect(ws_url)
        rows, cols = _terminal_dimensions()
        ws.send(json.dumps({"type": "resize", "cols": cols, "rows": rows}))
    except Exception:
        if ws is not None:
            _close_terminal_session(ws)
        console.print(
            f"[red]Could not connect to {computer_id}. Run `celesto computer ssh {computer_id}` again.[/red]"
        )
        raise typer.Exit(1)

    console.print("[dim]Connected. Press Ctrl+] to disconnect.[/dim]")

    stdin_fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(stdin_fd)
    done = threading.Event()
    terminal_failed = threading.Event()

    def recv_loop():
        try:
            while not done.is_set():
                try:
                    msg = ws.recv(timeout=1)
                except TimeoutError:
                    continue
                if isinstance(msg, str):
                    if _is_terminal_gateway_error(msg):
                        terminal_failed.set()
                        break
                    os.write(sys.stdout.fileno(), msg.encode("utf-8"))
                elif isinstance(msg, bytes):
                    os.write(sys.stdout.fileno(), msg)
        except websockets.exceptions.ConnectionClosed as e:
            if e.rcvd and e.rcvd.code != 1000:
                terminal_failed.set()
        except OSError:
            pass
        finally:
            done.set()

    def handle_sigwinch(*_args):
        nonlocal rows, cols
        try:
            new_rows, new_cols = _terminal_dimensions()
            if (new_rows, new_cols) != (rows, cols):
                rows, cols = new_rows, new_cols
                ws.send(json.dumps({"type": "resize", "cols": cols, "rows": rows}))
        except Exception:
            pass

    try:
        tty.setraw(stdin_fd)
        old_sigwinch = signal.signal(signal.SIGWINCH, handle_sigwinch)

        receiver = threading.Thread(target=recv_loop, daemon=True)
        receiver.start()

        while not done.is_set():
            try:
                readable, _, _ = select.select([stdin_fd], [], [], 0.2)
            except (OSError, ValueError):
                break
            if not readable:
                continue
            try:
                data = os.read(stdin_fd, 4096)
            except OSError:
                break
            if not data:
                break
            if b"\x1d" in data:
                break
            try:
                ws.send(data.decode("utf-8", errors="replace"))
            except (websockets.exceptions.ConnectionClosed, OSError):
                break

    except KeyboardInterrupt:
        pass
    finally:
        done.set()
        termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_settings)
        signal.signal(signal.SIGWINCH, old_sigwinch)
        _close_terminal_session(ws)
        console.print("\n[dim]Disconnected.[/dim]")

    if terminal_failed.is_set():
        console.print(
            f"[red]The terminal connection for {computer_id} ended unexpectedly. Run `celesto computer ssh {computer_id}` again.[/red]"
        )
        raise typer.Exit(1)


@app.command("stop")
def stop_computer(
    computer_id: Annotated[str, typer.Argument(help="Computer ID or name")],
    as_json: JsonOption = False,
    api_key: ApiKeyOption = None,
):
    """Stop a running computer."""
    with _get_client(api_key) as client:
        organization = None if as_json else client.organizations.active()
        result = client.computers.stop(computer_id)

    if as_json:
        _print_json(result)
        return

    if organization:
        console.print(
            f"[dim]Computer {computer_id} in {describe_organization(organization)} is being stopped.[/dim]"
        )
    else:
        console.print(f"[dim]Computer {computer_id} is being stopped.[/dim]")


@app.command("start")
def start_computer(
    computer_id: Annotated[str, typer.Argument(help="Computer ID or name")],
    as_json: JsonOption = False,
    api_key: ApiKeyOption = None,
):
    """Start a stopped computer."""
    with _get_client(api_key) as client:
        result = client.computers.start(computer_id)

    if as_json:
        _print_json(result)
        return

    console.print(f"[dim]Computer {computer_id} is being started.[/dim]")


@app.command("delete")
def delete_computer(
    computer_id: Annotated[str, typer.Argument(help="Computer ID or name")],
    force: Annotated[
        bool, typer.Option("--force", "-f", help="Skip confirmation")
    ] = False,
    as_json: JsonOption = False,
    api_key: ApiKeyOption = None,
):
    """Delete a computer."""
    with _get_client(api_key) as client:
        if not force and not as_json:
            # API keys are bound to one organization, and a .env in the working
            # directory can change which one. Name the target before deleting.
            organization = client.organizations.active()
            prompt = (
                f"Delete computer {computer_id} in {describe_organization(organization)}?"
                if organization
                else f"Delete computer {computer_id}?"
            )
            if not typer.confirm(prompt):
                raise typer.Abort()

        result = client.computers.delete(computer_id)

    if as_json:
        _print_json(result)
        return

    console.print(f"[dim]Computer {computer_id} is being deleted.[/dim]")
