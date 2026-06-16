# Google ADK Setup

## Install

```bash
pip install observra[adk]
```

## Usage

```python
import observra

observra.initialize(backend="jsonl", path="telemetry.jsonl")

# Your ADK agent code — telemetry is captured automatically
```

## Captured Events

- `model_response` — LLM calls with token counts and cost
- `tool_start` / `tool_end` — tool invocations with duration
- `agent_start` / `agent_end` — agent lifecycle with delegation depth
- `session_start` / `session_end` — session boundaries
