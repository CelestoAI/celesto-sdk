from __future__ import annotations

import re
from collections.abc import Iterator, MutableMapping
from typing import Any

from .exceptions import CelestoValidationError
from .types import ComputerTerminalSessionInfo, NetworkPolicy

_DISK_RE = re.compile(r"^\s*(?P<amount>\d+(?:\.\d+)?)\s*(?P<unit>[a-zA-Z]*)\s*$")
_DISK_UNITS_TO_MB = {
    "": 1,
    "m": 1,
    "mb": 1,
    "mib": 1,
    "g": 1024,
    "gb": 1024,
    "gib": 1024,
    "t": 1024 * 1024,
    "tb": 1024 * 1024,
    "tib": 1024 * 1024,
}


def parse_disk_size_mb(disk: int | float | str | None) -> int | None:
    """Parse a user-friendly disk size into megabytes."""
    if disk is None:
        return None

    if isinstance(disk, bool):
        raise CelestoValidationError(
            "disk must be a size in MB or a string like '2gb'."
        )

    if isinstance(disk, int):
        if disk <= 0:
            raise CelestoValidationError("disk must be greater than 0 MB.")
        return disk

    if isinstance(disk, float):
        if disk <= 0 or not disk.is_integer():
            raise CelestoValidationError(
                "disk as a number must be a whole number of MB."
            )
        return int(disk)

    if not isinstance(disk, str):
        raise CelestoValidationError(
            "disk must be a size in MB or a string like '2gb'."
        )

    match = _DISK_RE.match(disk)
    if not match:
        raise CelestoValidationError(
            "disk must be a size in MB or a string like '2gb'."
        )

    unit = match.group("unit").lower()
    multiplier = _DISK_UNITS_TO_MB.get(unit)
    if multiplier is None:
        raise CelestoValidationError(
            "disk must use MB, GB, or TB, for example '2048mb' or '2gb'."
        )

    size_mb = float(match.group("amount")) * multiplier
    if size_mb <= 0 or not size_mb.is_integer():
        raise CelestoValidationError(
            "disk must resolve to a whole number of MB, for example '1536mb' or '1.5gb'."
        )
    return int(size_mb)


def resolve_disk_size_mb(
    disk: int | float | str | None,
    disk_size_mb: int | None,
) -> int | None:
    """Resolve the friendly disk alias and the explicit API field."""
    parsed_disk = parse_disk_size_mb(disk)
    if parsed_disk is not None and disk_size_mb is not None:
        if parsed_disk != disk_size_mb:
            raise CelestoValidationError(
                "disk and disk_size_mb must have the same value when both are provided."
            )
        return disk_size_mb
    return disk_size_mb if disk_size_mb is not None else parsed_disk


def _make_client(
    *,
    client: Any | None,
    api_key: str | None,
    base_url: str | None,
) -> tuple[Any, bool]:
    if client is not None:
        return client, False

    from .client import _CelestoClient

    return _CelestoClient(api_key=api_key, base_url=base_url), True


class Computer(MutableMapping[str, Any]):
    """A convenience object for one Celesto computer.

    This is the high-level API for notebooks and scripts. Creating an instance
    creates a cloud computer immediately, stores the returned data, and lets you
    use both attribute and dictionary-style access.

    Example:
        >>> computer = Computer(memory=512, cpus=1, disk="2gb")
        >>> print(computer.name, computer["name"])
        >>> result = computer.run("uname -a")
        >>> computer.delete()
    """

    def __init__(
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
        api_key: str | None = None,
        base_url: str | None = None,
        client: Any | None = None,
    ):
        self._client, self._owns_client = _make_client(
            client=client,
            api_key=api_key,
            base_url=base_url,
        )
        self._data: dict[str, Any] = self._client.computers.create(
            cpus=cpus,
            memory=memory,
            vcpus=vcpus,
            ram_mb=ram_mb,
            disk_size_mb=resolve_disk_size_mb(disk, disk_size_mb),
            image=image,
            template_id=template_id,
            template_version=template_version,
            persistent_home=persistent_home,
            **(
                {"network_policy": network_policy} if network_policy is not None else {}
            ),
        )

    @classmethod
    def get(
        cls,
        computer_id: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        client: Any | None = None,
    ) -> "Computer":
        """Load an existing computer by name or ID."""
        instance = cls.__new__(cls)
        instance._client, instance._owns_client = _make_client(
            client=client,
            api_key=api_key,
            base_url=base_url,
        )
        instance._data = instance._client.computers.get(computer_id)
        return instance

    @classmethod
    def list(
        cls,
        *,
        status: str | None = None,
        template_id: str | None = None,
        project_id: str | None = None,
        limit: int | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        client: Any | None = None,
    ) -> list[dict[str, Any]]:
        """List computers in the current account."""
        sdk_client, owns_client = _make_client(
            client=client,
            api_key=api_key,
            base_url=base_url,
        )
        try:
            response = sdk_client.computers.list(
                status=status,
                template_id=template_id,
                project_id=project_id,
                limit=limit,
            )
        finally:
            if owns_client:
                sdk_client.close()
        computers = response.get("computers", []) if isinstance(response, dict) else []
        return list(computers)

    @classmethod
    def list_templates(
        cls,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        client: Any | None = None,
    ) -> list[dict[str, Any]]:
        """List available computer templates."""
        sdk_client, owns_client = _make_client(
            client=client,
            api_key=api_key,
            base_url=base_url,
        )
        try:
            templates = sdk_client.computers.list_templates()
        finally:
            if owns_client:
                sdk_client.close()
        return list(templates)

    @classmethod
    def templates(cls, **kwargs: Any) -> list[dict[str, Any]]:
        """Alias for list_templates()."""
        return cls.list_templates(**kwargs)

    @property
    def data(self) -> dict[str, Any]:
        """Return a copy of the latest computer data."""
        return dict(self._data)

    def _identifier(self) -> str:
        identifier = self._data.get("id") or self._data.get("name")
        if not isinstance(identifier, str) or not identifier:
            raise CelestoValidationError(
                "This computer does not have an ID yet. Call refresh() or create a computer first."
            )
        return identifier

    def refresh(self) -> "Computer":
        """Reload this computer's data from Celesto."""
        self._data = self._client.computers.get(self._identifier())
        return self

    def run(self, command: str, *, timeout: int = 30) -> dict[str, Any]:
        """Run a shell command on this computer."""
        return self._client.computers.exec(
            self._identifier(),
            command,
            timeout=timeout,
        )

    def exec(self, command: str, *, timeout: int = 30) -> dict[str, Any]:
        """Alias for run()."""
        return self.run(command, timeout=timeout)

    def run_stream(
        self,
        command: str,
        *,
        timeout: int = 30,
    ) -> Iterator[dict[str, Any]]:
        """Stream command output events from this computer."""
        return self._client.computers.exec_stream(
            self._identifier(),
            command,
            timeout=timeout,
        )

    def create_terminal_session(self) -> ComputerTerminalSessionInfo:
        """Create a short-lived direct terminal gateway connection."""
        return self._client.computers.create_terminal_session(self._identifier())

    def stop(self) -> "Computer":
        """Stop this computer and update the local data."""
        self._data = self._client.computers.stop(self._identifier())
        return self

    def start(self) -> "Computer":
        """Start this computer and update the local data."""
        self._data = self._client.computers.start(self._identifier())
        return self

    def delete(self) -> "Computer":
        """Delete this computer and update the local data."""
        self._data = self._client.computers.delete(self._identifier())
        return self

    def publish_port(self, port: int = 8000) -> str | None:
        """Publish a port and return its public URL when the API provides one."""
        published = self._client.computers.publish_port(self._identifier(), port=port)
        published_ports = list(self._data.get("published_ports") or [])
        published_ports = [
            item
            for item in published_ports
            if item.get("port") != published.get("port")
        ]
        published_ports.append(published)
        self._data["published_ports"] = published_ports
        url = published.get("url")
        return url if isinstance(url, str) else None

    def list_published_ports(self) -> list[dict[str, Any]]:
        """List public ports for this computer."""
        ports = self._client.computers.list_published_ports(self._identifier())
        self._data["published_ports"] = ports
        return ports

    def unpublish_port(self, port: int = 8000) -> dict[str, Any]:
        """Remove a public port route."""
        unpublished = self._client.computers.unpublish_port(
            self._identifier(),
            port=port,
        )
        self._data["published_ports"] = [
            item
            for item in self._data.get("published_ports") or []
            if item.get("port") != port
        ]
        return unpublished

    def close(self) -> None:
        """Close the underlying HTTP client when this object owns it."""
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "Computer":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return self._data[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value

    def __delitem__(self, key: str) -> None:
        del self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        name = self._data.get("name", "unknown")
        status = self._data.get("status", "unknown")
        return f"Computer(name={name!r}, status={status!r})"
