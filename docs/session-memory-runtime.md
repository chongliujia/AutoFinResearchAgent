# Session, Memory, and Agent Runtime

## Goal

AutoFinResearchAgent should behave like a Codex-style agent workspace, not a single-turn task form.

The user should be able to continue a thread:

```text
帮我分析 AAPL 10-K
重点看现金流
继续刚才那个
整理成 memo
```

That requires an explicit session layer, short-term memory, and a runtime that coordinates routing, policy, streaming, task execution, and memory updates.

## Current Implementation

The first implementation adds:

```text
autofin/session.py
autofin/memory.py
autofin/agent_runtime.py
```

### SessionStore

`SessionStore` owns conversation sessions.

Each session contains:

```text
session_id
title
messages
memory
created_at
updated_at
```

When persistence is enabled, sessions are written under:

```text
.autofin/sessions/
.autofin/sessions/transcripts/
.autofin/tasks/
```

The JSON file stores the latest session state. The JSONL transcript stores append-only message events for auditability.
Task records are stored separately so `active_task_id` can still load its result after the service restarts.

### SessionMemory

`SessionMemory` is deliberately small and inspectable.

It stores:

```text
summary
working_entities
pending_action
active_task_id
task_summaries
```

Examples:

```json
{
  "working_entities": {
    "last_intent": "research_sec_filing",
    "ticker": "AAPL",
    "filing_type": "10-K",
    "focus": ["cash flow"]
  },
  "pending_action": {
    "action": "show_run_research_card",
    "intent": "research_sec_filing",
    "ticker": "AAPL"
  },
  "active_task_id": "task-id",
  "task_summaries": [
    {
      "task_id": "task-id",
      "ticker": "AAPL",
      "filing_type": "10-K",
      "summary": "Analyzed filing text and extracted evidence-backed highlights.",
      "evidence_count": 2
    }
  ]
}
```

This is short-term thread memory, not a vector database and not hidden long-term personalization.

### AgentRuntime

`AgentRuntime` coordinates:

```text
message
  -> session context
  -> LLMIntentRouter
  -> PolicyEngine
  -> chat stream or Run Research card
  -> session memory update
  -> task creation when confirmed
```

The runtime injects session context into:

- LLM intent routing
- general chat response generation

When a research task completes, the task result is summarized back into session memory. This lets follow-up messages refer to the most recent company, filing, evidence, or task id.

The runtime also performs deterministic memory resolution after LLM routing. The LLM still decides the intent, but if it classifies a follow-up as `research_sec_filing` and omits fields such as `ticker` or `filing_type`, `AgentRuntime` can fill those from `SessionMemory.working_entities`. The response includes `resolved_from_memory` so the behavior is inspectable.

This lets the model resolve follow-up language such as:

```text
继续刚才那个
同一个公司
same filing
整理成 memo
```

## API

Sessions:

```http
GET /api/sessions
POST /api/sessions
GET /api/sessions/{session_id}
DELETE /api/sessions/{session_id}
DELETE /api/sessions
```

Chat requests now accept `session_id`:

```json
{
  "session_id": "session-...",
  "message": "继续刚才那个，重点看现金流"
}
```

Streaming responses include session metadata:

```text
event: chat-meta
data: {
  "session_id": "...",
  "session": {...},
  "routed_intent": {...},
  "policy_decision": {...}
}
```

## UI Behavior

The left `Sessions` panel now represents chat sessions instead of research tasks.

The UI:

- creates a session when needed
- deletes one session or clears all sessions after browser confirmation
- sends `session_id` with chat and Run Research requests
- keeps the chat transcript in the session
- binds a created research task back to the active session
- reloads the active task result from local task persistence after service restarts
- preserves the chat thread while task events stream into the conversation
- shows a right-side Memory panel with working entities, pending action, active task, and recent task summaries

## Design Rules

1. LLM routing uses session context, but execution policy remains deterministic.
2. Memory must be visible and serializable.
3. Session memory is allowed to summarize and resolve references, but it must not silently invent financial facts.
4. Research evidence and task traces remain separate from conversational memory.
5. Long-term memory should not be added until session memory is stable.

## Next Steps

1. Add explicit session summary refresh using an LLM summarizer.
2. Add more follow-up routing fixtures for references like "继续刚才那个公司".
3. Add cancel/pause/resume runtime actions.
4. Add a richer active task view per session.
5. Add local project memory for user preferences and research style.
