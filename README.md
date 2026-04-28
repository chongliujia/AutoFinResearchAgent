# AutoFinResearchAgent

AutoFinResearchAgent is a local-first, skill-based runtime for auditable financial research agents.

The project is being built as a financial research agent workspace: users can chat normally, describe research goals in natural language, and let the runtime turn executable research requests into structured tasks. LangGraph executes the workflow, skills do the domain work, and the UI exposes tool calls, evidence, traces, and results.

## Current MVP

The repository now contains a runnable Python MVP:

- LangGraph-backed research workflow
- LangChain-compatible skill abstraction
- Permission-aware skill registry
- In-process sandbox boundary for the first execution model
- Trace logging for auditability
- `sec_filing_analysis` skill backed by SEC filing metadata
- SEC submissions API client for filing metadata and source links
- FastAPI service layer
- Chat-first local Web UI inspired by agent apps such as Codex
- General conversation support without forcing every message into a task
- Server-Sent Events for task activity streaming
- Inline, collapsible tool-call cards in the chat flow
- Model API configuration through environment variables and the local UI
- LangChain structured-output parser for chat intent, with deterministic fallback
- Tests for runtime, permissions, skills, orchestrator, and Web API

## Architecture

```text
Web UI
  |
  v
FastAPI service
  |
  v
LangGraph research workflow
  |
  v
Skill runtime + sandbox boundary
```

The core design remains:

```text
Agent Runtime  -> decides and schedules
Skills         -> declare what they can do
Sandbox        -> controls how execution happens
Trace Log      -> records what happened
Evidence       -> keeps outputs grounded
```

The current workflow is:

```text
start_trace
  |
  v
select_skill
  |
  v
check_permissions
  |
  v
execute_skill
  |
  v
write_result_trace
```

## Project Layout

```text
autofin/
  runtime/
    orchestrator.py       # LangGraph workflow
    permissions.py        # permission policy
    skill_registry.py     # skill registration and selection
    trace.py              # JSONL trace logging
  sandbox/
    executor.py           # execution boundary
  skills/
    base.py               # Skill abstraction + LangChain tool adapter
    sec_filing.py         # SEC filing metadata skill
  data/
    sec_client.py         # SEC company ticker and submissions client
  intent.py               # chat intent parsing
  web/
    app.py                # FastAPI routes
    task_store.py         # in-memory task/session store
    static/               # local Web UI
  config.py               # model API configuration
  cli.py                  # CLI entrypoint
docs/
  architecture.md
  web-ui.md
tests/
```

## Development Environment

Use the existing conda environment `rag`:

```bash
source /Users/jiachongliu/anaconda3/etc/profile.d/conda.sh
conda activate rag
```

Install the package in editable mode:

```bash
pip install -e ".[dev]"
```

Run tests:

```bash
python -m pytest
```

Optional model API configuration:

```bash
export AUTOFIN_MODEL_PROVIDER=openai-compatible
export AUTOFIN_MODEL_NAME=
export AUTOFIN_MODEL_BASE_URL=
export AUTOFIN_MODEL_API_KEY=
export AUTOFIN_MODEL_TEMPERATURE=0.2
export AUTOFIN_SEC_USER_AGENT="AutoFinResearchAgent your-email@example.com"
```

You can also configure these values in the local Web UI. API keys are never returned by the API in plaintext.

UI-saved model settings persist locally:

```text
.autofin/config.json    # provider, model, base_url, temperature
.autofin/secrets.json   # api_key
```

The `.autofin/` directory is gitignored.

## CLI Usage

Run the current mock SEC filing skill through the LangGraph runtime:

```bash
python -m autofin.cli run sec_filing_analysis --ticker AAPL --filing-type 10-K
```

Start the local Web UI:

```bash
python -m autofin.cli serve --port 8098
```

Open:

```text
http://127.0.0.1:8098
```

## Web UI

The UI is chat-first, but the execution layer remains structured and auditable.

```text
User message
  |
  v
intent routing
  |
  +--> general conversation reply
  |
  +--> structured research task
  |
  v
LangGraph workflow
  |
  v
inline tool calls + right-side inspector
```

The current screen is organized as:

```text
Left:   Sessions + Skills + Model API
Center: Chat log + Composer
Right:  Current task + Activity + Result + Evidence
```

Example prompt:

```text
帮我分析 AAPL 最近的 10-K，重点看风险因素和现金流
```

The backend parses this into a structured task:

```json
{
  "ticker": "AAPL",
  "filing_type": "10-K",
  "focus": ["risk factors", "cash flow"]
}
```

If a model API key and model name are configured, `/api/chat` uses LangChain structured output to classify and parse the request. Without model configuration, it falls back to the deterministic parser so the app remains usable offline.

During execution, the chat stream shows collapsible tool-call cards:

```text
tool_call_requested: sec_filing_analysis
  inputs
  permissions

tool_call_completed: sec_filing_analysis
  trace_id
  evidence
```

## API

Health:

```http
GET /api/health
```

Skills:

```http
GET /api/skills
```

Model settings:

```http
GET /api/settings/model
POST /api/settings/model
```

Tasks:

```http
GET /api/tasks
POST /api/tasks
GET /api/tasks/{task_id}
GET /api/tasks/{task_id}/events
```

Chat:

```http
POST /api/chat
```

Example:

```bash
curl -sS http://127.0.0.1:8098/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"帮我分析 AAPL 最近的 10-K，重点看风险因素和现金流"}'
```

## Documentation

- [Architecture](docs/architecture.md)
- [Web UI Development Notes](docs/web-ui.md)

## Next Steps

1. Add SEC filing document download and section extraction.
2. Add SQLite-backed task/session persistence.
3. Add LangGraph checkpointing and task resume.
4. Use the configured model for filing summarization and memo generation.
5. Add a permission approval panel for network/filesystem access.
6. Add generated report artifacts and Markdown/HTML memo previews.
7. Migrate the static UI to React once the API shape stabilizes.
8. Wrap the Web UI with Tauri when the local desktop workflow is mature.
