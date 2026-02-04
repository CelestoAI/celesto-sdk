# Celesto SDK

[![PyPI version](https://badge.fury.io/py/celesto.svg)](https://pypi.org/project/celesto/)
[![Python](https://img.shields.io/pypi/pyversions/celesto.svg)](https://pypi.org/project/celesto/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

Python SDK and CLI for the [Celesto AI platform](https://celesto.ai) - Deploy and manage AI agents with built-in delegated access to user resources.

## What is Celesto?

Celesto is a managed AI platform that enables you to:
- **Deploy AI agents** to production with automatic scaling and monitoring
- **Manage delegated access** to end-user resources (Google Drive, etc.) through GateKeeper
- **Build faster** with infrastructure handled for you

## Features

- **Agent Deployment**: Deploy your AI agents as containerized applications with zero infrastructure management
- **GateKeeper**: Secure delegated access management with OAuth and fine-grained permissions for user resources
- **CLI & SDK**: Flexible interfaces for both interactive usage and programmatic integration
- **Project Organization**: Organize your agents and access rules by projects
- **Automatic Scaling**: Your agents scale automatically based on demand

## Installation

```bash
pip install celesto
```

**Requirements:** Python 3.10 or higher

## Quick Start

### 1. Get Your API Key

Sign up at [celesto.ai](https://celesto.ai) and get your API key from **Settings → Security**.

### 2. Configure Environment

```bash
export CELESTO_API_KEY="your-api-key-here"
export CELESTO_PROJECT_NAME="your-project-name"  # Optional: set default project
```

### 3. Deploy Your First Agent

```python
from celesto.sdk import CelestoSDK
from pathlib import Path

with CelestoSDK() as client:
    result = client.deployment.deploy(
        folder=Path("./my-agent"),
        name="my-agent",
        description="My AI assistant",
        project_name="My Project"
    )
    print(f"Deployed! Status: {result['status']}")
```

## Authentication

The SDK supports two authentication methods:

### Environment Variable (Recommended)

```bash
export CELESTO_API_KEY="your-api-key"
```

```python
from celesto.sdk import CelestoSDK

client = CelestoSDK()  # Automatically uses CELESTO_API_KEY
```

### Explicit API Key

```python
from celesto.sdk import CelestoSDK

client = CelestoSDK(api_key="your-api-key")
```

### Context Manager (Best Practice)

Use the context manager to ensure proper resource cleanup:

```python
with CelestoSDK() as client:
    deployments = client.deployment.list()
    # Resources automatically cleaned up
```

## Core Concepts

### Projects

Projects are organizational units that group your deployments and access connections. You can specify a project by:
- Setting `CELESTO_PROJECT_NAME` environment variable
- Passing `project_name` parameter to methods
- If not specified, the SDK uses your first available project

### Deployments

Deployments are your AI agents running on Celesto's managed infrastructure. Each deployment:
- Runs in an isolated container
- Scales automatically based on load
- Can have custom environment variables
- Belongs to a specific project

### GateKeeper

GateKeeper manages delegated access to end-user resources (like Google Drive). It handles:
- OAuth authorization flows
- Connection management per user (subject)
- Fine-grained access rules (folder/file permissions)
- Secure credential storage

## SDK Reference

### Deployment API

#### Deploy an Agent

```python
from pathlib import Path

result = client.deployment.deploy(
    folder=Path("./my-agent"),
    name="weather-bot",
    description="A bot that provides weather information",
    envs={
        "OPENAI_API_KEY": "sk-...",
        "DEBUG": "false"
    },
    project_name="My Project"
)

print(f"Deployment ID: {result['id']}")
print(f"Status: {result['status']}")  # "READY" or "BUILDING"
```

**Parameters:**
- `folder` (Path): Directory containing your agent code
- `name` (str): Unique deployment name
- `description` (str, optional): Human-readable description
- `envs` (dict, optional): Environment variables for your agent
- `project_name` (str, optional): Project to deploy to (defaults to `CELESTO_PROJECT_NAME` or first project)

**Excluding Files with .celestoignore:**

Create a `.celestoignore` file in your agent folder to exclude files and directories from deployment. The format is identical to `.gitignore`:

```gitignore
# Python artifacts
__pycache__/
*.pyc
*.pyo

# Virtual environments
venv/
.venv/

# Environment files
.env
.env.local

# Development files
.vscode/
.git/

# Dependencies
node_modules/

# Tests
tests/
*.test.py
```

Files and directories matching these patterns will be automatically excluded from the deployment bundle.

#### List Deployments

```python
deployments = client.deployment.list()

for dep in deployments:
    print(f"{dep['name']}: {dep['status']}")
```

### GateKeeper API

#### Connect a User (Initiate OAuth)

```python
# Initiate delegated access for a user
result = client.gatekeeper.connect(
    subject="user:john@example.com",
    project_name="my-project",
    provider="google_drive"
)

if oauth_url := result.get("oauth_url"):
    print(f"User must authorize at: {oauth_url}")
    # Send this URL to the user
elif result["status"] == "authorized":
    print("User already connected!")

print(f"Connection ID: {result['connection_id']}")
```

**Parameters:**
- `subject` (str): Unique user identifier (e.g., "user:email@example.com")
- `project_name` (str): Your project name
- `provider` (str): OAuth provider (default: "google_drive")
- `redirect_uri` (str, optional): Custom OAuth callback URL

#### List User's Google Drive Files

```python
files = client.gatekeeper.list_drive_files(
    project_name="my-project",
    subject="user:john@example.com",
    page_size=50,
    include_folders=True
)

for file in files["files"]:
    print(f"{file['name']} ({file['mimeType']})")

# Handle pagination
if next_token := files.get("next_page_token"):
    more_files = client.gatekeeper.list_drive_files(
        project_name="my-project",
        subject="user:john@example.com",
        page_token=next_token
    )
```

**Parameters:**
- `project_name` (str): Your project name
- `subject` (str): User identifier
- `page_size` (int): Results per page (1-1000, default: 20)
- `page_token` (str, optional): Token for pagination
- `folder_id` (str, optional): List specific folder
- `query` (str, optional): Google Drive search query
- `include_folders` (bool): Include folders in results (default: True)
- `order_by` (str, optional): Sort order

#### Configure Access Rules

Restrict which files/folders a user can access:

```python
# Allow access only to specific folders (recursive)
result = client.gatekeeper.update_access_rules(
    subject="user:john@example.com",
    project_name="my-project",
    allowed_folders=["1A2B3C4D5E6F", "7G8H9I0J1K2L"],  # Google Drive folder IDs
    allowed_files=[]  # Optional: specific file IDs
)

print(f"Access rules updated. Version: {result['version']}")
```

**Parameters:**
- `subject` (str): User identifier
- `project_name` (str): Your project name
- `allowed_folders` (list, optional): Folder IDs with recursive access
- `allowed_files` (list, optional): Individual file IDs
- `provider` (str, optional): Provider filter

#### List Connections

```python
result = client.gatekeeper.list_connections(
    project_name="my-project",
    status_filter="authorized"  # or "pending", "failed"
)

for conn in result["connections"]:
    print(f"{conn['subject']}: {conn['status']}")
```

#### Revoke Access

```python
result = client.gatekeeper.revoke_connection(
    subject="user:john@example.com",
    project_name="my-project"
)

print(f"Revoked connection: {result['id']}")
```

#### Clear Access Rules

Remove all restrictions (grant full access):

```python
# Get connection ID first
connections = client.gatekeeper.list_connections(project_name="my-project")
connection_id = connections["connections"][0]["id"]

# Clear rules
result = client.gatekeeper.clear_access_rules(connection_id)
print(f"Access unrestricted: {result['unrestricted']}")  # True
```

## CLI Reference

The Celesto CLI provides command-line access to all SDK features.

### Deployment Commands

```bash
# Deploy an agent
celesto deploy --project "My Project"

# List deployments
celesto ls
```

### A2A (Agent-to-Agent) Commands

```bash
# Get agent card
celesto a2a get-card --agent http://localhost:8000

# Additional A2A commands
celesto a2a --help
```

### General Commands

```bash
# Show help
celesto --help

# Show version
celesto --version
```

## Error Handling

The SDK provides specific exception types for different error scenarios:

```python
from celesto.sdk import CelestoSDK
from celesto.sdk.exceptions import (
    CelestoAuthenticationError,
    CelestoNotFoundError,
    CelestoValidationError,
    CelestoRateLimitError,
    CelestoServerError,
    CelestoNetworkError,
)

try:
    with CelestoSDK() as client:
        result = client.deployment.deploy(
            folder=Path("./my-agent"),
            name="my-agent",
            project_name="My Project"
        )
except CelestoAuthenticationError as e:
    print(f"Authentication failed: {e}")
    print("Check your API key at https://celesto.ai → Settings → Security")
except CelestoValidationError as e:
    print(f"Invalid input: {e}")
except CelestoNotFoundError as e:
    print(f"Resource not found: {e}")
except CelestoRateLimitError as e:
    print(f"Rate limit exceeded. Retry after {e.retry_after} seconds")
except CelestoServerError as e:
    print(f"Server error: {e}")
except CelestoNetworkError as e:
    print(f"Network error: {e}")
```

### Exception Types

- **CelestoAuthenticationError**: Invalid API key or unauthorized (401/403)
- **CelestoNotFoundError**: Resource not found (404)
- **CelestoValidationError**: Invalid request parameters (400/422)
- **CelestoRateLimitError**: Rate limit exceeded (429) - includes `retry_after` attribute
- **CelestoServerError**: Server-side errors (5xx)
- **CelestoNetworkError**: Network/connection failures

## Advanced Configuration

### Custom API Endpoint

```python
# For testing or custom deployments
client = CelestoSDK(
    api_key="your-key",
    base_url="https://custom-api.example.com/v1"
)
```

Or via environment variable:

```bash
export CELESTO_BASE_URL="https://custom-api.example.com/v1"
```

### Resource Cleanup

Always close the client when done, or use a context manager:

```python
# Manual cleanup
client = CelestoSDK()
try:
    deployments = client.deployment.list()
finally:
    client.close()

# Context manager (recommended)
with CelestoSDK() as client:
    deployments = client.deployment.list()
    # Automatically closed
```

## Examples

### Complete Deployment Workflow

```python
from celesto.sdk import CelestoSDK
from pathlib import Path
import os

# Set environment
os.environ["CELESTO_API_KEY"] = "your-api-key"

with CelestoSDK() as client:
    # Deploy agent
    deployment = client.deployment.deploy(
        folder=Path("./my-agent"),
        name="production-bot-v2",
        description="Production chatbot version 2",
        envs={
            "OPENAI_API_KEY": os.environ["OPENAI_API_KEY"],
            "ENVIRONMENT": "production"
        },
        project_name="Production"
    )

    print(f"Deployed: {deployment['id']}")
    print(f"Status: {deployment['status']}")

    # List all deployments
    all_deployments = client.deployment.list()
    print(f"\nTotal deployments: {len(all_deployments)}")
```

### Complete GateKeeper Workflow

```python
from celesto.sdk import CelestoSDK

with CelestoSDK() as client:
    project = "my-saas-app"
    user = "user:alice@example.com"

    # Step 1: Initiate connection
    conn = client.gatekeeper.connect(
        subject=user,
        project_name=project
    )

    if oauth_url := conn.get("oauth_url"):
        print(f"Send user to: {oauth_url}")
        # Wait for user to authorize...

    # Step 2: Configure access rules (limit to specific folders)
    rules = client.gatekeeper.update_access_rules(
        subject=user,
        project_name=project,
        allowed_folders=["shared_folder_id_123"]
    )
    print(f"Access rules set: {rules}")

    # Step 3: List accessible files
    files = client.gatekeeper.list_drive_files(
        project_name=project,
        subject=user,
        page_size=100
    )

    print(f"\nAccessible files: {len(files['files'])}")
    for file in files["files"]:
        print(f"  - {file['name']}")

    # Step 4: Revoke when done
    # client.gatekeeper.revoke_connection(
    #     subject=user,
    #     project_name=project
    # )
```

## Documentation

- **API Documentation**: https://docs.celesto.ai/celesto-sdk
- **Platform Guide**: https://celesto.ai/docs
- **Repository**: https://github.com/CelestoAI/sdk

## Support

- **Issues & Bugs**: [GitHub Issues](https://github.com/CelestoAI/sdk/issues)
- **Questions**: Create a discussion on GitHub
- **Email**: support@celesto.ai

## Contributing

We welcome contributions! Please see our contributing guidelines in the repository.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

## About

Created and maintained by the [Celesto AI](https://celesto.ai) team.

For more information about the Celesto platform, visit [celesto.ai](https://celesto.ai).
