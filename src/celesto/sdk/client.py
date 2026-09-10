import json
import os
import sys
import tarfile
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any, List, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pathspec

from .base import _BASE_URL, _BaseClient, _BaseConnection
from .computer import resolve_disk_size_mb
from .exceptions import (
    CelestoError,
    CelestoServerError,
    CelestoValidationError,
)
from .runtime.client import Agents, EndUsers, Runs, Sessions, Settings
from .types import ComputerTerminalSessionInfo, NetworkPolicy

__all__ = [
    "_BASE_URL",
    "Computers",
    "Deployment",
    "GateKeeper",
    "Organizations",
    "_BaseClient",
    "_BaseConnection",
    "_CelestoClient",
]

# Deployed proxies can terminate long idle buffered exec responses before the
# backend command timeout. Aggregate the existing streaming endpoint for longer
# commands while preserving the public exec() return shape.
_STREAM_EXEC_FOR_TIMEOUT_OVER_SECONDS = 110


def _terminal_gateway_url(gateway_url: str, token: str) -> str:
    """Add the short-lived terminal token to a gateway WebSocket URL."""
    parts = urlsplit(gateway_url)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key != "token"
    ]
    query.append(("token", token))
    return urlunsplit(parts._replace(query=urlencode(query)))


class Deployment(_BaseClient):
    """Client for deploying agents to Celesto.

    Deploy your AI agents to Celesto's managed infrastructure with automatic
    scaling and monitoring. Agents are packaged and deployed as containerized
    applications.

    Example:
        client = _CelestoClient()

        # Deploy an agent
        result = client.deployment.deploy(
            folder=Path("./my-agent"),
            name="my-agent",
            description="My AI assistant",
            envs={"OPENAI_API_KEY": "sk-..."},
            project_name="My Project"
        )
        print(f"Deployment ID: {result['id']}")

        # List all deployments
        deployments = client.deployment.list()
    """

    def _resolve_project_id(self, project_name: str) -> str:
        """Resolve a project ID from a project name."""
        skip = 0
        limit = 100
        while True:
            response = self._request(
                "GET",
                "/projects/",
                params={"skip": skip, "limit": limit},
            )
            projects = response.get("data") or []
            for project in projects:
                if project.get("name") == project_name:
                    project_id = project.get("id")
                    if not project_id:
                        raise CelestoValidationError(
                            f"Project '{project_name}' missing id in response."
                        )
                    return project_id
            total = response.get("total")
            if total is None:
                break
            skip += limit
            if skip >= total:
                break

        raise CelestoValidationError(f"Project '{project_name}' not found.")

    def _resolve_first_project_id(self) -> str:
        """Resolve the first available project ID."""
        response = self._request(
            "GET",
            "/projects/",
            params={"skip": 0, "limit": 1},
        )
        projects = response.get("data") or []
        if not projects:
            raise CelestoValidationError(
                "No projects found. Create a project or specify project_name."
            )
        project_id = projects[0].get("id")
        if not project_id:
            raise CelestoValidationError("First project missing id in response.")
        return project_id

    def _load_ignore_patterns(self, folder: Path) -> pathspec.PathSpec | None:
        """Load ignore patterns from .celestoignore file if it exists.

        Args:
            folder: The folder to search for .celestoignore

        Returns:
            PathSpec object if .celestoignore exists, None otherwise
        """
        ignore_file = folder / ".celestoignore"
        if not ignore_file.exists():
            return None

        try:
            with open(ignore_file, "r", encoding="utf-8") as f:
                patterns = f.read().splitlines()

            # Process patterns according to gitignore spec:
            # 1. Lines starting with # (after whitespace) are comments
            # 2. Inline comments: # preceded by space (e.g., "pattern # comment")
            # 3. # without preceding space is literal (e.g., "file#name")
            processed_patterns = []
            for line in patterns:
                # Strip inline comments: only ' #' (space followed by #) starts a comment
                # Find the first occurrence of ' #' pattern
                space_hash_idx = line.find(" #")
                if space_hash_idx >= 0:
                    # Strip from the space before # onwards
                    line = line[:space_hash_idx]

                # Strip leading/trailing whitespace
                line = line.strip()

                # Skip empty lines and full-line comments (lines starting with #)
                if not line or line.startswith("#"):
                    continue

                processed_patterns.append(line)

            return pathspec.PathSpec.from_lines("gitignore", processed_patterns)
        except OSError as e:
            print(f"Warning: Failed to read .celestoignore file: {e}", file=sys.stderr)
            print("Continuing deployment without file filtering.", file=sys.stderr)
            return None
        except Exception as e:
            print(
                f"Warning: Failed to parse .celestoignore patterns: {e}",
                file=sys.stderr,
            )
            print("Continuing deployment without file filtering.", file=sys.stderr)
            return None

    def _create_deployment(
        self,
        bundle: Path,
        name: str,
        description: str,
        envs: dict[str, str],
        project_id: str,
    ) -> dict:
        """Internal method to upload and create a deployment."""
        if bundle.exists() and not bundle.is_file():
            raise CelestoValidationError(f"Bundle {bundle} is not a file")

        # multi part form data where bundle is the file upload
        config = {"env": envs or {}}

        # JSON encode the config since multipart form data doesn't support nested dicts
        form_data = {
            "name": name,
            "description": description,
            "project_id": project_id,
            "config": json.dumps(config),
        }

        # Multipart form data with file upload
        with open(bundle, "rb") as f:
            files = {"code_bundle": ("app_bundle.tar.gz", f.read(), "application/gzip")}
            return self._request("POST", "/deploy/agent", files=files, data=form_data)

    def deploy(
        self,
        folder: Path,
        name: str,
        description: Optional[str] = None,
        envs: Optional[dict[str, str]] = None,
        project_name: Optional[str] = None,
    ) -> dict:
        """Deploy an agent from a local folder.

        Packages the folder contents into a tar.gz archive and deploys it
        to Celesto. The folder should contain your agent code and any
        configuration files (e.g., requirements.txt, Dockerfile).

        If a .celestoignore file exists in the folder, files and directories
        matching the patterns in that file will be excluded from deployment.
        The format is identical to .gitignore.

        Args:
            folder: Path to the folder containing agent code
            name: Unique name for the deployment
            description: Human-readable description (optional)
            envs: Environment variables to inject (optional)
            project_name: Project name to scope the deployment (optional; defaults to first project)

        Returns:
            Deployment result with 'id', 'status', and other metadata

        Raises:
            CelestoValidationError: If folder doesn't exist or isn't a directory

        Example:
            result = client.deployment.deploy(
                folder=Path("./my-agent"),
                name="weather-bot",
                description="A bot that provides weather information",
                envs={"API_KEY": "secret123"},
                project_name="My Project"
            )
            print(f"Status: {result['status']}")  # "READY" or "BUILDING"
        """
        if not folder.exists():
            raise CelestoValidationError(f"Folder {folder} does not exist")
        if not folder.is_dir():
            raise CelestoValidationError(f"Folder {folder} is not a directory")

        resolved_project_name = project_name or os.environ.get("CELESTO_PROJECT_NAME")
        if resolved_project_name:
            resolved_project_id = self._resolve_project_id(resolved_project_name)
        else:
            resolved_project_id = self._resolve_first_project_id()

        # Load ignore patterns from .celestoignore if it exists
        ignore_spec = self._load_ignore_patterns(folder)

        # Create tar.gz archive (Nixpacks expects tar.gz format)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".tar.gz") as temp_file:
            with tarfile.open(temp_file.name, "w:gz") as tar:
                # Recursively add all files, respecting .celestoignore patterns
                for root, dirs, files in os.walk(folder):
                    root_path = Path(root)
                    rel_root = root_path.relative_to(folder)

                    # Filter directories in-place to avoid descending into ignored dirs
                    if ignore_spec:
                        # Check each directory and remove ignored ones
                        dirs_to_remove = []
                        for d in dirs:
                            rel_dir = rel_root / d if rel_root != Path(".") else Path(d)
                            # PathSpec needs forward slashes and trailing slash for dirs
                            dir_pattern = str(rel_dir).replace("\\", "/") + "/"
                            if ignore_spec.match_file(dir_pattern):
                                dirs_to_remove.append(d)
                        for d in dirs_to_remove:
                            dirs.remove(d)

                    # Add files that aren't ignored
                    for file in files:
                        file_path = root_path / file
                        rel_file = (
                            rel_root / file if rel_root != Path(".") else Path(file)
                        )

                        # Skip if file matches ignore patterns
                        if ignore_spec:
                            # PathSpec needs forward slashes
                            file_pattern = str(rel_file).replace("\\", "/")
                            if ignore_spec.match_file(file_pattern):
                                continue

                        # Add file to archive with relative path
                        arcname = str(rel_file).replace("\\", "/")
                        tar.add(file_path, arcname=arcname)
            bundle = Path(temp_file.name)

        try:
            return self._create_deployment(
                bundle, name, description, envs, resolved_project_id
            )
        finally:
            bundle.unlink()

    def list(self) -> List[dict]:
        """List all deployments for your account.

        Returns:
            List of deployment objects with id, name, status, etc.

        Example:
            deployments = client.deployment.list()
            for dep in deployments:
                print(f"{dep['name']}: {dep['status']}")
        """
        return self._request("GET", "/deploy/apps")


class GateKeeper(_BaseClient):
    """Client for GateKeeper - delegated access management.

    GateKeeper enables secure delegated access to end-user resources like
    Google Drive. Users authorize access via OAuth, and you can configure
    fine-grained access rules to limit which files/folders are accessible.

    Typical flow:
        1. Call connect() to initiate OAuth for a user
        2. User completes OAuth flow via the returned URL
        3. Configure access rules with update_access_rules()
        4. List files with list_drive_files()

    Example:
        client = _CelestoClient()

        # Initiate connection for a user
        result = client.gatekeeper.connect(
            subject="user:john@example.com",
            project_name="my-project"
        )
        if result.get("oauth_url"):
            print(f"User must authorize: {result['oauth_url']}")

        # After authorization, list their files
        files = client.gatekeeper.list_drive_files(
            project_name="my-project",
            subject="user:john@example.com"
        )
    """

    def connect(
        self,
        *,
        subject: str,
        project_name: str,
        provider: str = "google_drive",
        redirect_uri: str | None = None,
    ) -> dict:
        """Initiate a delegated access connection for a user.

        Creates a new connection or returns an existing one. If the user
        hasn't authorized yet, returns an OAuth URL they must visit.

        Args:
            subject: Unique identifier for the end-user (e.g., "user:email@example.com")
            project_name: Your project name to scope the connection
            provider: OAuth provider (default: "google_drive")
            redirect_uri: Custom OAuth redirect URI (optional)

        Returns:
            Dict with 'connection_id', 'status', and optionally 'oauth_url'
            - status: "pending" (needs OAuth), "authorized", or "failed"
            - oauth_url: Present if user needs to complete OAuth

        Example:
            result = client.gatekeeper.connect(
                subject="user:demo",
                project_name="my-project"
            )
            if oauth_url := result.get("oauth_url"):
                print(f"Please authorize: {oauth_url}")
            elif result["status"] == "authorized":
                print("Already connected!")
        """
        payload: dict[str, str] = {
            "subject": subject,
            "provider": provider,
            "project_name": project_name,
        }
        if redirect_uri:
            payload["redirect_uri"] = redirect_uri

        return self._request("POST", "/gatekeeper/connect", json_body=payload)

    def list_connections(
        self,
        *,
        project_name: str,
        status_filter: str | None = None,
    ) -> dict:
        """List all delegated access connections for a project.

        Args:
            project_name: Project name to filter connections
            status_filter: Optional filter by status ("pending", "authorized", "failed")

        Returns:
            Dict with 'connections' list

        Example:
            result = client.gatekeeper.list_connections(
                project_name="my-project",
                status_filter="authorized"
            )
            for conn in result["connections"]:
                print(f"{conn['subject']}: {conn['status']}")
        """
        params: dict[str, str] = {"project_name": project_name}
        if status_filter:
            params["status_filter"] = status_filter

        return self._request("GET", "/gatekeeper/connections", params=params)

    def get_connection(self, connection_id: str) -> dict:
        """Get details of a specific connection.

        Args:
            connection_id: The connection ID

        Returns:
            Connection details including status, subject, provider, etc.

        Raises:
            CelestoNotFoundError: If connection doesn't exist
        """
        return self._request("GET", f"/gatekeeper/connections/{connection_id}")

    def revoke_connection(
        self,
        *,
        subject: str,
        project_name: str,
        provider: str | None = None,
    ) -> dict:
        """Revoke a delegated access connection by subject.

        Finds and revokes the connection for the given subject within the
        specified project. The user will need to re-authorize to regain access.

        Args:
            subject: Subject identifier (e.g., "user:email@example.com")
            project_name: Project name to scope the revocation
            provider: Optional provider filter (e.g., "google_drive")

        Returns:
            Confirmation of revocation with connection ID

        Raises:
            CelestoNotFoundError: If no connection found for the subject

        Example:
            result = client.gatekeeper.revoke_connection(
                subject="user:john@example.com",
                project_name="my-project"
            )
            print(f"Revoked connection: {result['id']}")
        """
        params: dict[str, str] = {
            "subject": subject,
            "project_name": project_name,
        }
        if provider:
            params["provider"] = provider

        return self._request("DELETE", "/gatekeeper/connections", params=params)

    def list_drive_files(
        self,
        *,
        project_name: str,
        subject: str,
        page_size: int = 20,
        page_token: str | None = None,
        folder_id: str | None = None,
        query: str | None = None,
        include_folders: bool = True,
        order_by: str | None = None,
    ) -> dict:
        """
        List Google Drive files for a delegated subject.

        If access rules are configured and no folder_id is specified,
        files from all allowed folders will be returned automatically.
        When access rules are active, a page may contain fewer than page_size
        results after filtering. Use next_page_token to continue.

        Args:
            project_name: Project name to scope the access
            subject: Subject identifier (end-user)
            page_size: Number of files per page (1-1000, default 20)
            page_token: Page token from previous response for pagination
            folder_id: Specific folder ID to list (optional)
            query: Google Drive search query (optional)
            include_folders: Whether to include folders in results
            order_by: Google Drive orderBy parameter (optional)

        Returns:
            Dict with 'files' list and optional 'next_page_token'
        """
        params: dict[str, object] = {
            "project_name": project_name,
            "subject": subject,
            "page_size": page_size,
            "include_folders": include_folders,
        }
        if page_token:
            params["page_token"] = page_token
        if folder_id:
            params["folder_id"] = folder_id
        if query:
            params["query"] = query
        if order_by:
            params["order_by"] = order_by

        return self._request("GET", "/gatekeeper/connectors/drive/files", params=params)

    # Access Rules Management

    def get_access_rules(self, connection_id: str) -> dict:
        """
        Get access rules for a delegated access connection.

        Args:
            connection_id: The connection ID

        Returns:
            Dict with 'version', 'allowed_folders', 'allowed_files', and 'unrestricted' flag
        """
        return self._request(
            "GET", f"/gatekeeper/connections/{connection_id}/access-rules"
        )

    def update_access_rules(
        self,
        *,
        subject: str,
        project_name: str,
        allowed_folders: List[str] | None = None,
        allowed_files: List[str] | None = None,
        provider: str | None = None,
    ) -> dict:
        """
        Update access rules for a delegated access connection by subject.

        Files in allowed_folders (and their subfolders) will be accessible.
        Individual files can be added via allowed_files.
        Setting both to empty lists blocks all access. Use clear_access_rules()
        to remove restrictions.

        Args:
            subject: Subject identifier (e.g., "user:email@example.com")
            project_name: Project name to scope the update
            allowed_folders: List of Google Drive folder IDs with recursive access
            allowed_files: List of individual Google Drive file IDs
            provider: Optional provider filter (e.g., "google_drive")

        Returns:
            Updated access rules dict

        Example:
            result = client.gatekeeper.update_access_rules(
                subject="user:john@example.com",
                project_name="my-project",
                allowed_folders=["folder_id_1", "folder_id_2"],
            )
        """
        params: dict[str, str] = {
            "subject": subject,
            "project_name": project_name,
        }
        if provider:
            params["provider"] = provider

        payload = {
            "allowed_folders": allowed_folders or [],
            "allowed_files": allowed_files or [],
        }
        return self._request(
            "PUT",
            "/gatekeeper/connections/access-rules",
            params=params,
            json_body=payload,
        )

    def clear_access_rules(self, connection_id: str) -> dict:
        """
        Clear access rules for a connection (set to unrestricted).

        This removes all file/folder restrictions, giving the subject
        full access to all files in their Google Drive.

        Args:
            connection_id: The connection ID

        Returns:
            Access rules dict with 'unrestricted': True
        """
        return self._request(
            "DELETE", f"/gatekeeper/connections/{connection_id}/access-rules"
        )


class Computers(_BaseClient):
    """Client for managing sandboxed computers (AI sandboxes).

    Provides methods to create, list, execute commands on, and manage
    virtual machine sandboxes for AI agents and development.

    Internal wrapper for the public ``Computer`` resource class.
    """

    def create(
        self,
        *,
        cpus: int | None = None,
        memory: int | None = None,
        disk: int | float | str | None = None,
        vcpus: int | None = None,
        ram_mb: int | None = None,
        disk_size_mb: int | None = None,
        image: str | None = None,
        template_id: str | None = None,
        template_version: str | None = None,
        persistent_home: bool | None = None,
        network_policy: NetworkPolicy | None = None,
    ) -> dict[str, Any]:
        """Create a new sandboxed computer.

        Resource fields are optional. If omitted, Celesto creates a scratch
        computer with the default size.

        Args:
            cpus: Number of virtual CPUs (1-16). Alias for vcpus.
            memory: Memory in MB (512-32768). Alias for ram_mb.
            disk: Disk size as MB or a string like "2gb". Alias for disk_size_mb.
            vcpus: Number of virtual CPUs (1-16).
            ram_mb: Memory in MB (512-32768).
            disk_size_mb: Disk size in MB (512-51200).
            image: Legacy OS image selector.
            template_id: Sandbox template id, such as "scratch" or
                "coding-agent". Use this when you want preinstalled tools.
            template_version: Optional immutable template version.
            network_policy: {"mode": "open"} (default) or {"mode": "off"}.
                Fixed after creation. Internet off requires persistent_home=False.
            persistent_home: Whether to keep ``/home/ohm`` across stop and
                restore. Off by default and cannot be changed after create.

        Returns:
            Computer info dict with id, status, resources, template, etc.
        """
        if cpus is not None and vcpus is not None and cpus != vcpus:
            raise CelestoValidationError(
                "cpus and vcpus must have the same value when both are provided."
            )
        if memory is not None and ram_mb is not None and memory != ram_mb:
            raise CelestoValidationError(
                "memory and ram_mb must have the same value when both are provided."
            )

        resolved_vcpus = vcpus if vcpus is not None else cpus
        resolved_ram_mb = ram_mb if ram_mb is not None else memory
        resolved_disk_size_mb = resolve_disk_size_mb(disk, disk_size_mb)

        if network_policy is not None:
            if (
                not isinstance(network_policy, dict)
                or set(network_policy) != {"mode"}
                or network_policy["mode"] not in ("open", "off")
            ):
                raise CelestoValidationError(
                    'network_policy must be {"mode": "open"} or {"mode": "off"}.'
                )
            if network_policy["mode"] == "off" and persistent_home:
                raise CelestoValidationError(
                    "External volumes require internet access; set persistent_home=False."
                )

        payload: dict[str, Any] = {}
        if network_policy is not None:
            payload["network_policy"] = dict(network_policy)
        if resolved_vcpus is not None:
            payload["vcpus"] = resolved_vcpus
        if resolved_ram_mb is not None:
            payload["ram_mb"] = resolved_ram_mb
        if resolved_disk_size_mb is not None:
            payload["disk_size_mb"] = resolved_disk_size_mb
        if image is not None:
            payload["image"] = image
        if template_id is not None:
            payload["template_id"] = template_id
        if template_version is not None:
            payload["template_version"] = template_version
        if persistent_home is not None:
            payload["external_volume_enabled"] = persistent_home

        return self._request(
            "POST",
            "/computers",
            json_body=payload,
            timeout=self._timeout_with_read(600),
        )

    def list_templates(self) -> list[dict[str, Any]]:
        """List available sandbox templates.

        Returns:
            List of template dicts with id, display_name, description, default
            resources, version, and experimental fields.
        """
        return self._request("GET", "/computers/templates")

    def list(
        self,
        *,
        status: str | None = None,
        template_id: str | None = None,
        project_id: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """List all computers in the current organization.

        Args:
            status: Optional status filter, such as "running" or "stopped".
            template_id: Optional template filter, such as "coding-agent".
            project_id: Optional project ID filter.
            limit: Optional maximum number of computers to return.

        Returns:
            Dict with "computers" list and "count".
        """
        params: dict[str, Any] = {}
        if status is not None:
            params["status"] = status
        if template_id is not None:
            params["template_id"] = template_id
        if project_id is not None:
            params["project_id"] = project_id
        if limit is not None:
            params["limit"] = limit

        return self._request("GET", "/computers", params=params or None)

    def get(self, computer_id: str) -> dict[str, Any]:
        """Get details of a specific computer.

        Args:
            computer_id: Computer ID (e.g., "cmp_xxx").

        Returns:
            Computer info dict.
        """
        return self._request("GET", f"/computers/{computer_id}")

    def create_terminal_session(self, computer_id: str) -> ComputerTerminalSessionInfo:
        """Create a short-lived direct terminal gateway connection.

        Args:
            computer_id: Computer ID or name.

        Returns:
            Terminal session details. ``url`` is ready for a WebSocket client
            and contains a short-lived secret token.
        """
        session = self._request("POST", f"/computers/{computer_id}/terminals")
        terminal_id = session.get("terminal_id") if isinstance(session, dict) else None
        gateway_url = session.get("gateway_url") if isinstance(session, dict) else None
        token = session.get("token") if isinstance(session, dict) else None
        expires_at = session.get("expires_at") if isinstance(session, dict) else None
        if (
            not isinstance(terminal_id, str)
            or not isinstance(gateway_url, str)
            or not isinstance(token, str)
            or not isinstance(expires_at, str)
        ):
            raise CelestoServerError(
                "Celesto did not return terminal connection details. Call create_terminal_session() again."
            )
        return {
            "terminal_id": terminal_id,
            "gateway_url": gateway_url,
            "token": token,
            "expires_at": expires_at,
            "url": _terminal_gateway_url(gateway_url, token),
        }

    def publish_port(self, computer_id: str, port: int = 8000) -> dict[str, Any]:
        """Publish a computer port to the internet.

        Args:
            computer_id: Computer ID or name.
            port: Application port to publish (1024-65535). Each computer supports up to four public ports.

        Returns:
            Published port dict with id, computer_id, port, url, status, and created_at.
        """
        return self._request(
            "POST",
            f"/computers/{computer_id}/published-ports",
            json_body={"port": port},
        )

    def list_published_ports(self, computer_id: str) -> List[dict[str, Any]]:
        """List active published ports for a computer.

        Args:
            computer_id: Computer ID or name.

        Returns:
            List of published port dicts.
        """
        return self._request("GET", f"/computers/{computer_id}/published-ports")

    def unpublish_port(self, computer_id: str, port: int = 8000) -> dict[str, Any]:
        """Remove a published computer port.

        Args:
            computer_id: Computer ID or name.
            port: Published application port to remove (1024-65535).

        Returns:
            Unpublished port dict.
        """
        return self._request(
            "DELETE", f"/computers/{computer_id}/published-ports/{port}"
        )

    def exec(
        self,
        computer_id: str,
        command: str,
        *,
        timeout: int = 30,
    ) -> dict[str, Any]:
        """Execute a command on a running computer.

        Args:
            computer_id: Computer ID.
            command: Shell command to execute.
            timeout: Timeout in seconds (1-300).

        Returns:
            Dict with exit_code, stdout, stderr.
        """
        if timeout > _STREAM_EXEC_FOR_TIMEOUT_OVER_SECONDS:
            return self._exec_via_stream(
                computer_id,
                command,
                timeout=timeout,
            )

        return self._request(
            "POST",
            f"/computers/{computer_id}/exec",
            json_body={"command": command, "timeout": timeout},
            timeout=self._timeout_with_read(timeout + 15),
        )

    def _exec_via_stream(
        self,
        computer_id: str,
        command: str,
        *,
        timeout: int,
    ) -> dict[str, Any]:
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        exit_code: int | None = None
        duration_ms: int | None = None
        timed_out: bool | None = None
        command_id: str | None = None

        for event in self.exec_stream(computer_id, command, timeout=timeout):
            if command_id is None and isinstance(event.get("command_id"), str):
                command_id = event["command_id"]

            if event.get("stdout") is not None:
                stdout_parts.append(str(event["stdout"]))
            if event.get("stderr") is not None:
                stderr_parts.append(str(event["stderr"]))

            event_type = event.get("type")
            if event_type == "stdout":
                stdout_parts.append(str(event.get("data", "")))
            elif event_type == "stderr":
                stderr_parts.append(str(event.get("data", "")))

            if "exit_code" in event:
                raw_exit_code = event.get("exit_code")
                if isinstance(raw_exit_code, int):
                    exit_code = raw_exit_code
                elif (
                    isinstance(raw_exit_code, str)
                    and raw_exit_code.lstrip("-").isdigit()
                ):
                    exit_code = int(raw_exit_code)
                else:
                    exit_code = 1
                raw_duration_ms = event.get("duration_ms")
                if isinstance(raw_duration_ms, int):
                    duration_ms = raw_duration_ms
                if "timed_out" in event:
                    timed_out = bool(event.get("timed_out"))

        if exit_code is None:
            raise CelestoServerError(
                "Command stream ended before the remote exit status was received."
            )

        result: dict[str, Any] = {
            "exit_code": exit_code,
            "stdout": "".join(stdout_parts),
            "stderr": "".join(stderr_parts),
        }
        if command_id is not None:
            result["command_id"] = command_id
        if duration_ms is not None:
            result["duration_ms"] = duration_ms
        if timed_out is not None:
            result["timed_out"] = timed_out
        return result

    def exec_stream(
        self,
        computer_id: str,
        command: str,
        *,
        timeout: int = 30,
    ) -> Iterator[dict[str, Any]]:
        """Stream command output from a running computer.

        Args:
            computer_id: Computer ID.
            command: Shell command to execute.
            timeout: Timeout in seconds (1-300).

        Yields:
            Stream event dicts from the backend. Events may include stdout,
            stderr, data, stream, type, and exit_code fields.
        """
        return self._stream_request(
            "POST",
            f"/computers/{computer_id}/exec/stream",
            json_body={"command": command, "timeout": timeout},
            timeout=self._timeout_with_read(timeout + 15),
        )

    def list_command_history(
        self,
        computer_id: str,
        *,
        limit: int | None = None,
    ) -> Any:
        """List prior commands for a computer.

        This wraps the existing backend command-history endpoint without adding
        a new CLI shape.

        Args:
            computer_id: Computer ID or name.
            limit: Optional maximum number of history entries to return.

        Returns:
            Backend command-history payload.
        """
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit

        return self._request(
            "GET",
            f"/computers/{computer_id}/commands",
            params=params or None,
        )

    def stop(self, computer_id: str) -> dict[str, Any]:
        """Stop a running computer.

        Args:
            computer_id: Computer ID.

        Returns:
            Updated computer info.
        """
        return self._request("POST", f"/computers/{computer_id}/stop")

    def start(self, computer_id: str) -> dict[str, Any]:
        """Start a stopped computer.

        Args:
            computer_id: Computer ID.

        Returns:
            Updated computer info.
        """
        return self._request("POST", f"/computers/{computer_id}/start")

    def delete(self, computer_id: str) -> dict[str, Any]:
        """Delete a computer.

        Args:
            computer_id: Computer ID.

        Returns:
            Updated computer info.
        """
        return self._request("DELETE", f"/computers/{computer_id}")


class Organizations(_BaseClient):
    """Read-only view of the organization the current API key acts on."""

    def get(self, organization_id: str) -> dict[str, Any]:
        """Fetch a single organization by ID.

        Args:
            organization_id: ID of the organization to fetch.

        Returns:
            The organization record as returned by the API.

        Raises:
            CelestoAuthenticationError: If the key may not read the organization.
            CelestoNotFoundError: If no organization has that ID.
            CelestoServerError: If the API fails to answer.
        """
        return self._request("GET", f"/organizations/{organization_id}")

    def active(self) -> dict[str, Any] | None:
        """Resolve the organization this API key is bound to.

        API keys are bound to exactly one organization, but the API has no
        whoami endpoint, and ``GET /organizations/`` lists every organization
        the owning *user* belongs to rather than the one the key acts on. Read
        the bound organization back off a project instead: project listings are
        already scoped to the key's organization.

        Returns:
            A mapping with "id" and "name" for the bound organization, or None
            when it cannot be determined: the projects request failed, the
            organization has no projects, or the project carries no
            organization ID. When the project lookup succeeds but fetching the
            organization fails, "name" is None and only "id" is populated.

        Note:
            Never raises. Callers use this to label output, so a failure to
            resolve degrades to None rather than breaking the command.
        """
        try:
            response = self._request(
                "GET", "/projects/", params={"skip": 0, "limit": 1}
            )
        except CelestoError:
            return None

        projects = response.get("data") or []
        if not projects:
            return None

        organization_id = projects[0].get("organization_id")
        if not organization_id:
            return None

        try:
            organization = self.get(organization_id)
        except CelestoError:
            return {"id": organization_id, "name": None}
        return {"id": organization_id, "name": organization.get("name")}


class _CelestoClient(_BaseConnection):
    """Internal service client used by the CLI and high-level resource classes.

    Public computer code should use ``from celesto import Computer``. This
    lower-level client keeps shared HTTP behavior in one place for CLI commands,
    integrations, and resource wrappers.

    The client automatically reads API keys from the CELESTO_API_KEY environment
    variable if not provided explicitly. Use as a context manager for automatic
    resource cleanup.

    Args:
        api_key: Your Celesto API key. If not provided, reads from CELESTO_API_KEY
            environment variable.
        base_url: Custom API base URL (optional, for testing)
        organization_id: Organization to act as (optional)

    Raises:
        CelestoAuthenticationError: If no API key is found

    Example:
        # Using environment variable (recommended)
        import os
        os.environ["CELESTO_API_KEY"] = "your-api-key"

        with _CelestoClient() as client:
            # Deploy an agent
            result = client.deployment.deploy(
                folder=Path("./my-app"),
                name="My App",
                project_name="My Project"
            )

            # Manage delegated access
            connections = client.gatekeeper.list_connections(
                project_name="My Project"
            )
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        organization_id: str | None = None,
    ):
        super().__init__(api_key, base_url, organization_id)
        self.deployment = Deployment(self)
        self.gatekeeper = GateKeeper(self)
        self.computers = Computers(self)
        self.organizations = Organizations(self)
        # Managed agents: agents you define once and run for your end users.
        self.agents = Agents(self)
        self.runs = Runs(self)
        self.sessions = Sessions(self)
        self.end_users = EndUsers(self)
        self.settings = Settings(self)
