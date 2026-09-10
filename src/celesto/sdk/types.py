"""
Type definitions for Celesto SDK responses.

These TypedDict definitions provide better IDE support and type checking
for API responses. They represent the structure of data returned by
the Celesto API.
"""

from typing import List, Literal

from typing_extensions import NotRequired, TypedDict

# ============================================================================
# Deployment Types
# ============================================================================


class DeploymentInfo(TypedDict):
    """Information about a deployment."""

    id: str
    name: str
    description: NotRequired[str]
    status: Literal["READY", "BUILDING", "FAILED", "STOPPED"]
    created_at: NotRequired[str]
    updated_at: NotRequired[str]


class DeploymentResponse(TypedDict):
    """Response from deploy()."""

    id: str
    name: str
    status: Literal["READY", "BUILDING", "FAILED"]
    message: NotRequired[str]


# ============================================================================
# GateKeeper Types
# ============================================================================


ConnectionStatus = Literal["pending", "authorized", "failed", "revoked"]


class ConnectionResponse(TypedDict):
    """Response from connect()."""

    connection_id: str
    status: ConnectionStatus
    oauth_url: NotRequired[str]
    subject: NotRequired[str]
    provider: NotRequired[str]


class ConnectionInfo(TypedDict):
    """Detailed connection information."""

    connection_id: str
    subject: str
    provider: str
    status: ConnectionStatus
    project_name: str
    created_at: NotRequired[str]


class ConnectionListResponse(TypedDict):
    """Response from list_connections()."""

    connections: List[ConnectionInfo]


class DriveFile(TypedDict):
    """A Google Drive file or folder."""

    id: str
    name: str
    mimeType: str
    size: NotRequired[str]
    modifiedTime: NotRequired[str]
    createdTime: NotRequired[str]
    parents: NotRequired[List[str]]


class DriveFilesResponse(TypedDict):
    """Response from list_drive_files()."""

    files: List[DriveFile]
    next_page_token: NotRequired[str]


class AccessRules(TypedDict):
    """Access rules for a connection."""

    version: int
    allowed_folders: List[str]
    allowed_files: List[str]
    unrestricted: bool


# ============================================================================
# Computer Types
# ============================================================================

ComputerStatus = Literal[
    "creating",
    "running",
    "stopping",
    "stopped",
    "starting",
    "restoring",
    "restorable",
    "deleting",
    "deleted",
    "error",
]


class ComputerConnectionInfo(TypedDict):
    """Connection details for a running computer."""

    ssh: NotRequired[str]
    access_url: NotRequired[str]


class ComputerTerminalSessionInfo(TypedDict):
    """Short-lived connection details for the fast terminal gateway."""

    terminal_id: str
    gateway_url: str
    token: str
    expires_at: str
    url: str


PublishedPortStatus = Literal[
    "publishing",
    "published",
    "unpublishing",
    "unpublished",
    "error",
]


class ComputerPublishedPortInfo(TypedDict):
    """Information about a public computer port route."""

    id: NotRequired[str | None]
    computer_id: str
    port: int
    url: NotRequired[str | None]
    status: PublishedPortStatus
    created_at: NotRequired[str | None]


class NetworkPolicy(TypedDict):
    """Outbound internet access; fixed when the computer is created."""

    mode: Literal["open", "off"]


class ComputerInfo(TypedDict):
    """Information about a computer."""

    network_policy: NotRequired[NetworkPolicy]
    id: str
    name: str
    status: ComputerStatus
    vcpus: int
    ram_mb: int
    disk_size_mb: int
    image: str
    template_id: str
    template_version: NotRequired[str | None]
    connection: NotRequired[ComputerConnectionInfo | None]
    published_ports: NotRequired[List[ComputerPublishedPortInfo]]
    last_error: NotRequired[str | None]
    created_at: str
    stopped_at: NotRequired[str | None]


class SandboxTemplateInfo(TypedDict):
    """A sandbox template available for computer creation."""

    id: str
    display_name: str
    description: str
    default_vcpus: int
    default_ram_mb: int
    default_disk_size_mb: int
    version: NotRequired[str | None]
    experimental: bool
    aliases: NotRequired[List[str]]
    capabilities: NotRequired[List[str]]
    preinstalled_tools: NotRequired[List[str]]
    recommended_for: NotRequired[List[str]]
    default_published_ports: NotRequired[List[int]]
    has_playwright_browsers: NotRequired[bool]
    has_browser_system_deps: NotRequired[bool]


class ComputerListResponse(TypedDict):
    """Response from list computers."""

    computers: List[ComputerInfo]
    count: int


class ComputerExecResponse(TypedDict):
    """Response from executing a command."""

    exit_code: int
    stdout: str
    stderr: str


class ComputerCommandHistoryEntry(TypedDict):
    """A prior command execution for a computer."""

    command_id: str
    source: str
    status: str
    started_at: NotRequired[str | None]
    ended_at: NotRequired[str | None]
    duration_ms: NotRequired[int | None]
    timeout_seconds: NotRequired[int | None]
    exit_code: NotRequired[int | None]
    stdout_bytes: NotRequired[int | None]
    stderr_bytes: NotRequired[int | None]
    error_type: NotRequired[str | None]


class ComputerCommandHistoryResponse(TypedDict):
    """Response from listing prior command executions."""

    commands: List[ComputerCommandHistoryEntry]
    count: int


# ============================================================================
# Export all types
# ============================================================================

__all__ = [
    # Deployment
    "DeploymentInfo",
    "DeploymentResponse",
    # GateKeeper
    "ConnectionStatus",
    "ConnectionResponse",
    "ConnectionInfo",
    "ConnectionListResponse",
    "DriveFile",
    "DriveFilesResponse",
    "AccessRules",
    # Computer
    "ComputerStatus",
    "ComputerConnectionInfo",
    "ComputerTerminalSessionInfo",
    "PublishedPortStatus",
    "ComputerPublishedPortInfo",
    "ComputerInfo",
    "NetworkPolicy",
    "SandboxTemplateInfo",
    "ComputerListResponse",
    "ComputerExecResponse",
    "ComputerCommandHistoryEntry",
    "ComputerCommandHistoryResponse",
]
