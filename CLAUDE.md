# Celesto SDK - AI Assistant Guide

This document provides guidance for AI assistants working on the Celesto SDK codebase.

## Project Overview

**Celesto SDK** is a Python client library and CLI tool for the [Celesto AI platform](https://celesto.ai). It enables developers to:
- Deploy AI agents to managed infrastructure with automatic scaling
- Manage delegated access to user resources (Google Drive, etc.) via GateKeeper
- Interact with the platform through both programmatic SDK and command-line interfaces

**Current Version:** 0.0.2
**License:** Apache 2.0
**Python:** 3.10+
**API Base:** `https://api.celesto.ai/v1`

## Repository Structure

```
celesto-sdk/
├── src/celesto/           # Main package
│   ├── sdk/               # SDK implementation
│   │   ├── client.py      # Core SDK classes: CelestoSDK, Deployment, GateKeeper
│   │   ├── exceptions.py  # Custom exception hierarchy
│   │   ├── types.py       # Type definitions
│   │   └── __init__.py    # SDK public API exports
│   ├── main.py            # CLI entry point (Typer app)
│   ├── deployment.py      # CLI deployment commands
│   ├── a2a.py             # CLI agent-to-agent commands
│   ├── proxy.py           # CLI MCP proxy helper
│   └── __init__.py        # Package version and exports
├── tests/                 # Test suite
│   ├── test_sdk.py        # SDK unit tests
│   └── test_deployment.py # Deployment tests
├── pyproject.toml         # Project metadata, dependencies, tooling config
├── README.md              # User-facing documentation
├── AGENTS.md              # GitHub Copilot instructions
└── LICENSE                # Apache 2.0 license
```

## Architecture

### Three-Layer Design

1. **SDK Layer** ([src/celesto/sdk/client.py](src/celesto/sdk/client.py))
   - `CelestoSDK`: Main client class with context manager support
   - `Deployment`: Agent deployment operations
   - `GateKeeper`: Delegated access management
   - `_BaseConnection`: HTTP session and authentication management
   - `_BaseClient`: Shared HTTP request handling and error processing

2. **CLI Layer** ([src/celesto/main.py](src/celesto/main.py))
   - Typer-based CLI application
   - Commands: `deploy`, `list`/`ls`, `a2a`, `proxy`
   - Rich console output for better UX

3. **Shared Infrastructure**
   - Exception hierarchy in [sdk/exceptions.py](src/celesto/sdk/exceptions.py)
   - Type definitions in [sdk/types.py](src/celesto/sdk/types.py)

## Key Components

### 1. CelestoSDK Client

**File:** [src/celesto/sdk/client.py](src/celesto/sdk/client.py)

The main SDK client provides a unified interface to all Celesto services:

```python
with CelestoSDK() as client:
    # Deployment operations
    client.deployment.deploy(...)
    client.deployment.list()

    # GateKeeper operations
    client.gatekeeper.connect(...)
    client.gatekeeper.list_drive_files(...)
```

**Important patterns:**
- Context manager for automatic resource cleanup
- API key auto-detection from `CELESTO_API_KEY` environment variable
- Project resolution from `CELESTO_PROJECT_NAME` or first available project
- httpx-based HTTP client with bearer token authentication

### 2. Deployment API

**Class:** `Deployment` in [src/celesto/sdk/client.py](src/celesto/sdk/client.py:229)

**Key methods:**
- `deploy(folder, name, description, envs, project_name)` - Deploy agent from local folder
- `list()` - List all deployments
- `_resolve_project_id(project_name)` - Convert project name to ID
- `_load_ignore_patterns(folder)` - Load `.celestoignore` patterns if present
- `_create_deployment(bundle, name, description, envs, project_id)` - Upload tar.gz bundle

**Deployment flow:**
1. Resolve project ID (by name or use first available)
2. Load `.celestoignore` patterns if file exists
3. Recursively walk directory tree, filtering ignored files/directories
4. Create tar.gz archive of agent folder (excluding ignored items)
5. Upload as multipart form data with metadata
6. Return deployment status (READY or BUILDING)

**File filtering with .celestoignore:**
- Place a `.celestoignore` file in your agent folder to exclude files from deployment
- Format is identical to `.gitignore` (uses gitignore-style pattern matching)
- Supports patterns like `*.pyc`, `__pycache__/`, `node_modules/`, `.env`, etc.
- Comments (lines starting with `#`) and empty lines are ignored
- Inline comments supported: ` #` (space before `#`) starts a comment; `#` without space is literal (e.g., `file#name`)
- Directories are filtered before recursion for efficiency
- Implementation uses the `pathspec` library with `gitignore` pattern type

### 3. GateKeeper API

**Class:** `GateKeeper` in [src/celesto/sdk/client.py](src/celesto/sdk/client.py:404)

**Key methods:**
- `connect(subject, project_name, provider, redirect_uri)` - Initiate OAuth connection
- `list_connections(project_name, status_filter)` - List all connections
- `revoke_connection(subject, project_name, provider)` - Revoke access
- `list_drive_files(project_name, subject, ...)` - List user's Google Drive files
- `update_access_rules(subject, project_name, allowed_folders, allowed_files)` - Set access restrictions
- `clear_access_rules(connection_id)` - Remove all restrictions

**Access control model:**
- **Subject**: Unique identifier for end-user (e.g., "user:email@example.com")
- **Connection**: OAuth authorization between subject and provider
- **Access Rules**: Optional restrictions on accessible files/folders
- **Unrestricted**: Default state with full access to user's resources

### 4. Exception Hierarchy

**File:** [src/celesto/sdk/exceptions.py](src/celesto/sdk/exceptions.py)

```
CelestoError (base)
├── CelestoAuthenticationError (401/403)
├── CelestoNotFoundError (404)
├── CelestoValidationError (400/422)
├── CelestoRateLimitError (429) - includes retry_after
├── CelestoServerError (5xx)
└── CelestoNetworkError (connection failures)
```

All exceptions include `message` and optional `response` attributes.

### 5. CLI Commands

**File:** [src/celesto/main.py](src/celesto/main.py)

```bash
celesto deploy              # Deploy agent (interactive or --folder)
celesto list / ls           # List deployments
celesto a2a <subcommand>    # Agent-to-agent utilities
celesto proxy <subcommand>  # MCP proxy commands
```

## Development Setup

### Prerequisites
- Python 3.10 or higher
- `uv` (recommended) or `pip`

### Installation

```bash
# With uv (recommended)
pip install uv
uv venv
uv sync

# With pip
pip install -e .
```

### Running Tests

```bash
uv run pytest
# or
pytest
```

### Code Quality

```bash
# Linting
uv run ruff check .

# Formatting
uv run ruff format .

# Both at once
uv run ruff check . && uv run ruff format .
```

## Development Guidelines

### Code Style

1. **Formatting:** Ruff (similar to Black)
2. **Import sorting:** isort profile in Ruff
3. **Type hints:** Use throughout, especially in public APIs
4. **Docstrings:** Google-style docstrings for all public methods
5. **Line length:** Follows Ruff defaults

### Error Handling Patterns

Always map HTTP status codes to specific exceptions:

```python
def _handle_response(self, response: httpx.Response) -> Any:
    if status in (200, 201, 204):
        return response.json()
    if status in (401, 403):
        raise CelestoAuthenticationError(...)
    if status == 404:
        raise CelestoNotFoundError(...)
    # ... etc
```

### Authentication Flow

1. Check explicit `api_key` parameter
2. Fall back to `CELESTO_API_KEY` environment variable
3. Raise `CelestoAuthenticationError` if not found
4. Add to session headers as `Authorization: Bearer <key>`

### Project Resolution

For deployment operations:
1. Check method `project_name` parameter
2. Fall back to `CELESTO_PROJECT_NAME` environment variable
3. If not set, use first project from `/projects/` API
4. Paginate through projects to find match if needed

### Resource Management

Always support context manager protocol:

```python
class CelestoSDK(_BaseConnection):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        self.session.close()
```

## Common Tasks

### Adding a New SDK Method

1. Add method to appropriate client class (`Deployment` or `GateKeeper`)
2. Use `self._request()` for HTTP calls with proper error handling
3. Add docstring with Args, Returns, Raises, and Example sections
4. Update type hints in [sdk/types.py](src/celesto/sdk/types.py) if needed
5. Add tests in [tests/test_sdk.py](tests/test_sdk.py)

### Adding a New CLI Command

1. Add function to appropriate CLI module ([deployment.py](src/celesto/deployment.py), [a2a.py](src/celesto/a2a.py), etc.)
2. Use Typer decorators for arguments/options
3. Import and register in [main.py](src/celesto/main.py)
4. Use Rich for console output
5. Handle errors with try/except and user-friendly messages

### Updating API Endpoints

The API base URL is configurable:
- Default: `https://api.celesto.ai/v1`
- Override: `CELESTO_BASE_URL` environment variable
- Constructor: `CelestoSDK(base_url="...")`

When adding new endpoints:
- Use relative paths (e.g., `/deploy/apps`, not full URL)
- Include trailing slashes consistently (see [client.py:260](src/celesto/sdk/client.py#L260))
- Document query parameters and request body format

### Working with .celestoignore

When deploying agents, users can create a `.celestoignore` file to exclude files and directories from deployment:

**Example .celestoignore:**
```gitignore
# Python
__pycache__/
*.pyc
*.pyo
*.pyd

# Virtual environments
venv/
.venv/
env/

# Environment files
.env
.env.local

# IDE
.vscode/
.idea/
*.swp

# Dependencies
node_modules/

# Build artifacts
dist/
build/

# Tests
tests/
*.test.py

# Logs
*.log
logs/
```

**Implementation details:**
- Uses `pathspec` library with `gitignore` pattern matching (same as git)
- Loaded via `_load_ignore_patterns()` method in `Deployment` class
- Directories are filtered before recursion for performance
- Files are checked with forward-slash paths for cross-platform compatibility
- Empty lines and comments (starting with `#`) are automatically filtered out
- Inline comments supported per gitignore spec: ` #` (space before `#`) starts a comment, but `#` without preceding space is literal (e.g., `file#name` matches literally)
- If `.celestoignore` doesn't exist, deployment proceeds without filtering
- If `.celestoignore` can't be read or parsed, a warning is printed to stderr and deployment continues without filtering
- Comprehensive test suite in [tests/test_celestoignore.py](tests/test_celestoignore.py) and [tests/test_celestoignore_spec.py](tests/test_celestoignore_spec.py)

### Working with Multipart Uploads

For file uploads (like deployment bundles):

```python
with open(bundle, "rb") as f:
    files = {"code_bundle": ("app_bundle.tar.gz", f.read(), "application/gzip")}
    return self._request("POST", "/deploy/agent", files=files, data=form_data)
```

Note: Don't use `json_body` with `files` - use `data` for form fields.

## Testing

### Test Structure

- [tests/test_sdk.py](tests/test_sdk.py) - SDK client unit tests
- [tests/test_deployment.py](tests/test_deployment.py) - Deployment-specific tests

### Running Tests

```bash
# All tests
uv run pytest

# Specific test file
uv run pytest tests/test_sdk.py

# With verbose output
uv run pytest -v

# With coverage
uv run pytest --cov=src/celesto
```

### Test Dependencies

- pytest >= 8.4.1
- pytest-asyncio >= 0.21.0 (for async tests if needed)

## Important Notes

### Breaking Changes

This is a v0.x SDK, so:
- Public API may change between minor versions
- Always maintain backward compatibility within patch versions
- Document breaking changes in commit messages

### Security Considerations

- Never log API keys or sensitive data
- Validate all file paths before operations
- Use tarfile safely (avoid path traversal)
- Don't include credentials in error messages

### Dependencies

**Core:**
- httpx >= 0.27.0 (HTTP client)
- typer >= 0.20.0 (CLI framework)
- rich >= 14.0.0 (console output)
- python-dotenv >= 1.0.0 (environment variables)
- pathspec >= 0.11.0 (gitignore-style pattern matching for .celestoignore)
- a2a-sdk >= 0.3.10 (agent-to-agent protocol)
- fastmcp >= 2.7.1 (MCP support)

**Dev:**
- pytest >= 8.4.1
- ruff >= 0.12.4

### Release Process

1. Update version in [src/celesto/__init__.py](src/celesto/__init__.py)
2. Update [README.md](README.md) if needed
3. Commit changes
4. Tag release: `git tag v0.0.x`
5. Push to GitHub: `git push origin main --tags`
6. Build and publish to PyPI

## API Reference

### Deployment Endpoints

- `POST /deploy/agent` - Deploy new agent (multipart form)
- `GET /deploy/apps` - List deployments
- `GET /projects/` - List projects (with pagination)

### GateKeeper Endpoints

- `POST /gatekeeper/connect` - Initiate OAuth connection
- `GET /gatekeeper/connections` - List connections
- `GET /gatekeeper/connections/{id}` - Get connection details
- `DELETE /gatekeeper/connections` - Revoke connection by subject
- `GET /gatekeeper/connectors/drive/files` - List Drive files
- `GET /gatekeeper/connections/{id}/access-rules` - Get access rules
- `PUT /gatekeeper/connections/access-rules` - Update access rules by subject
- `DELETE /gatekeeper/connections/{id}/access-rules` - Clear access rules

## Troubleshooting

### Common Issues

**"API key not found"**
- Set `CELESTO_API_KEY` environment variable
- Or pass `api_key=` parameter to `CelestoSDK()`
- Get key from https://celesto.ai → Settings → Security

**"Project not found"**
- Set `CELESTO_PROJECT_NAME` environment variable
- Or pass `project_name=` parameter to methods
- Verify project exists at https://celesto.ai

**Import errors**
- Run `uv sync` or `pip install -e .`
- Check Python version >= 3.10

**Tests failing**
- Ensure dependencies are installed
- Check for API changes (mocks may be outdated)
- Run `uv run pytest -v` for detailed output

## Additional Resources

- **API Documentation:** https://docs.celesto.ai/celesto-sdk
- **Platform Guide:** https://celesto.ai/docs
- **Repository:** https://github.com/CelestoAI/sdk
- **Issue Tracker:** https://github.com/CelestoAI/sdk/issues
- **PyPI:** https://pypi.org/project/celesto/

## Contact

- **Support:** support@celesto.ai
- **Maintainer:** Aniket Maurya (aniket@celesto.ai)
