# Celesto SDK

Python SDK and CLI for the Celesto AI platform.

## Install

```bash
pip install celesto
```

## Configure

Set your API key in the environment:

```bash
export CELESTO_API_KEY="your-key"
export CELESTO_PROJECT_NAME="your-project-name"
```

## CLI

```bash
celesto deploy --project "My Project"
celesto ls
celesto a2a get-card --agent http://localhost:8000
```

## SDK

```python
from celesto.sdk import CelestoSDK

client = CelestoSDK()
print(client.deployment.list())
```
