# Intent Routing Design

## 目标

AutoFinResearchAgent 不能把每一句话都当成任务执行。用户可能是在普通对话、询问系统能力、配置模型、要求研究 SEC filing、要求生成报告，或者只是表达一个模糊想法。

Intent routing 的目标是：

- 判断用户消息应该进入哪条处理路径
- 从自然语言里抽取结构化字段
- 判断是否缺少必要信息
- 判断是否需要用户确认
- 保持执行层可控、可审计、可测试

LLM 可以负责识别和抽取，但不能直接执行工具或修改状态。后端策略层根据 intent 决定下一步。

## 当前问题

当前代码里的 intent 能力还比较粗：

```text
conversation
research_task
```

这会导致几个问题：

- 普通对话和研究任务边界不够细
- `research_task` 太宽，后面很难扩展 market data、news、report writing
- UI 无法清晰展示模型判断
- 后端不能根据不同 intent 做不同确认策略
- 测试样本无法覆盖真实用户表达的复杂性

## 目标 Intent Taxonomy

第一阶段建议支持这些 intent：

```text
general_chat
explain_app
configure_settings
research_sec_filing
research_market_data
research_news
compare_companies
write_report
unknown
```

### general_chat

普通闲聊、概念解释、非执行型问题。

示例：

```text
你好，你能做什么？
解释一下什么是 10-K
你和普通 ChatGPT 有什么区别？
```

行为：

```text
stream model reply
do not create task
do not call tools
```

### explain_app

询问本系统能力、使用方式、UI、配置、执行流程。

示例：

```text
这个项目怎么用？
右侧 Evidence 是什么？
为什么要配置 Model API？
```

行为：

```text
stream model reply grounded in local app capabilities
do not create task
```

### configure_settings

用户想配置模型、API key、SEC user-agent、数据源。

示例：

```text
我要配置 DeepSeek API
怎么设置模型 key？
SEC User-Agent 在哪配？
```

行为：

```text
reply with guidance
optionally highlight/open settings panel later
do not transmit secrets automatically
```

### research_sec_filing

要求分析 SEC filing、10-K、10-Q、risk factors、MD&A、现金流等。

示例：

```text
帮我分析 AAPL 最近的 10-K，重点看风险因素和现金流
看一下 MSFT 最新 10-Q 的收入增长
比较 NVDA 年报里的主要风险
```

行为：

```text
if ticker missing -> ask clarification
if ticker present -> propose or create LangGraph task
emit tool-call cards
write trace
```

### research_market_data

要求行情、价格、估值指标、财务 ratio。

示例：

```text
看一下 AAPL 最近一年股价表现
NVDA 现在 PE 大概多少？
```

行为：

```text
route to market_data_skill once implemented
currently ask clarification or explain unsupported
```

### research_news

要求新闻、事件、舆情、催化剂。

示例：

```text
最近 TSLA 有什么重要新闻？
总结一下苹果最近的监管风险
```

行为：

```text
route to news_monitor_skill once implemented
currently ask clarification or explain unsupported
```

### compare_companies

多公司比较。

示例：

```text
比较 MSFT 和 GOOGL 的云业务风险
AAPL 和 Samsung 最近财务表现谁更稳？
```

行为：

```text
extract multiple tickers/entities
route to comparison workflow once implemented
```

### write_report

要求整理成 memo、报告、Markdown、投资备忘录。

示例：

```text
把刚才的分析整理成一页 memo
生成 Markdown 报告
```

行为：

```text
if source task exists -> report_writing_skill
if no source -> ask which task/data to use
```

### unknown

模型无法确定，或信心不足。

行为：

```text
ask a focused clarification
do not create task
```

## RoutedIntent Schema

建议把当前 `ResearchIntent` 升级为 `RoutedIntent`：

```json
{
  "intent": "research_sec_filing",
  "confidence": 0.91,
  "assistant_reply": "",
  "ticker": "AAPL",
  "company_names": [],
  "filing_type": "10-K",
  "focus": ["risk factors", "cash flow"],
  "time_range": "latest",
  "output_format": null,
  "missing_fields": [],
  "needs_confirmation": true,
  "unsupported_reason": null
}
```

Field notes:

- `intent`: route name from taxonomy
- `confidence`: model confidence, 0 to 1
- `assistant_reply`: direct reply for non-task intents or clarification
- `ticker`: primary ticker if one is clear
- `company_names`: unresolved companies when ticker is unknown
- `filing_type`: `10-K`, `10-Q`, or null
- `focus`: research focus areas
- `time_range`: latest, FY2024, last quarter, last 12 months, etc.
- `output_format`: memo, markdown, table, chart, etc.
- `missing_fields`: required fields still missing
- `needs_confirmation`: whether backend should ask before task execution
- `unsupported_reason`: why this route cannot execute yet

## LLM Prompt Contract

The model should classify and extract only. It should not claim that it has run analysis.

Prompt constraints:

```text
You are an intent router for a local financial research agent.
Return only JSON matching the schema.
Do not run tools.
Do not fabricate data.
Classify ordinary conversation as general_chat.
Only classify executable research when the user asks for analysis, data retrieval, comparison, monitoring, or report generation.
Set missing_fields when required fields are absent.
Set needs_confirmation true for actions that start research workflows.
```

## Backend Policy

The backend owns execution decisions.

```text
RoutedIntent
  |
  v
Policy layer
  |
  +-- general_chat -> stream reply
  +-- explain_app -> stream reply
  +-- configure_settings -> stream guidance
  +-- research_sec_filing -> validate fields -> create task or ask clarification
  +-- unsupported intent -> explain current limitation
  +-- unknown -> ask clarification
```

Important rule:

```text
LLM intent classification is advisory.
Backend policy is authoritative.
```

## Confirmation Strategy

Not every intent should immediately execute.

Recommended first-phase behavior:

```text
general_chat         -> no confirmation
explain_app          -> no confirmation
configure_settings   -> no confirmation unless saving secrets
research_sec_filing  -> create visible Run Research card
write_report         -> confirm source task / output format
unknown              -> clarification
```

For the current project, a practical first step is:

- `Send`: normal chat
- `Run Research`: force research task creation from current composer text
- model route chip shows what the router inferred

This avoids surprising execution while still letting the router help.

## UI Design

The UI should expose model routing decisions without overwhelming the user.

Recommended components:

```text
Intent chip:
  research_sec_filing · 0.91

Missing fields:
  Needs ticker

Action card:
  Analyze AAPL 10-K
  Focus: risk factors, cash flow
  [Run research]
```

For general chat:

```text
Intent chip:
  general_chat
```

For unsupported intents:

```text
Intent chip:
  research_market_data · unsupported
Assistant:
  Market data skill is not implemented yet. I can add it next.
```

## Routing Failure Strategy

LLM routing can fail due to:

- no API key
- model timeout
- invalid JSON
- unsupported structured output
- provider-specific schema limitations

Routing hierarchy:

```text
LLM structured output
  ↓
LLM JSON prompt
  ↓
intent_routing_failed
```

The app should not silently fall back from a configured LLM router to deterministic rules. Silent fallback makes it difficult to know whether the product is actually using the configured model.

The response should expose routing metadata:

```json
{
  "router": "langchain_error",
  "intent": "intent_routing_failed",
  "router_error": "..."
}
```

## Test Strategy

Create a fixed routing evaluation set:

```text
tests/fixtures/intent_cases.jsonl
```

Each row:

```json
{
  "message": "帮我分析 AAPL 最近的 10-K，重点看风险因素和现金流",
  "expected_intent": "research_sec_filing",
  "expected_ticker": "AAPL",
  "expected_filing_type": "10-K"
}
```

Test categories:

- English general chat
- Chinese general chat
- app explanation
- settings questions
- SEC filing research
- missing ticker
- company name without ticker
- market data unsupported
- report writing without source
- ambiguous requests

Unit tests should use fake routers, not real model calls.

Optional manual evaluation can use the configured model and print mismatch summaries.

## Policy Learning / RL Roadmap

Intent routing should be designed so it can later support policy learning, but the project should not start with full reinforcement learning.

The reason is practical:

- There is not enough real user interaction data yet.
- The action space is still changing.
- Rewards are not well-defined.
- Direct RL could optimize the wrong behavior before the product loop is stable.

The recommended path is:

```text
Rule + LLM Router
  ↓
Policy logging
  ↓
Offline evaluation
  ↓
Explicit and implicit feedback
  ↓
Preference learning / contextual bandit
  ↓
Full RL only if needed
```

### Policy Layer

Add a policy layer between routing and execution:

```text
User message
  ↓
IntentRouter
  ↓
PolicyEngine
  ↓
Executor / UI action
```

The LLM router classifies and extracts fields. The `PolicyEngine` decides what the product should do.

Example policy actions:

```text
stream_chat
ask_clarification
show_run_research_card
create_research_task
run_skill
write_report
show_settings_guidance
unsupported_response
```

This separation matters because the LLM should not directly execute tools, save settings, start tasks, or transmit secrets.

### PolicyDecision Schema

Suggested schema:

```json
{
  "decision_id": "uuid",
  "intent": "research_sec_filing",
  "confidence": 0.91,
  "action": "show_run_research_card",
  "reason": "Ticker and filing type are present, but research execution should be explicit.",
  "requires_confirmation": true,
  "missing_fields": [],
  "created_task_id": null
}
```

### Policy Log

Every routing and policy decision should be logged.

Suggested JSONL event:

```json
{
  "timestamp": "2026-04-28T00:00:00Z",
  "session_id": "session-123",
  "message": "帮我分析 AAPL 最近的 10-K，重点看风险因素和现金流",
  "routed_intent": {
    "intent": "research_sec_filing",
    "confidence": 0.91,
    "ticker": "AAPL",
    "filing_type": "10-K"
  },
  "policy_decision": {
    "action": "show_run_research_card",
    "requires_confirmation": true
  },
  "outcome": {
    "user_clicked_run": null,
    "task_success": null,
    "feedback": null,
    "latency_ms": null
  }
}
```

This log creates the dataset needed for later evaluation and learning.

### Feedback Signals

Use both explicit and implicit feedback.

Explicit:

```text
thumbs_up
thumbs_down
user_comment
mark_as_wrong_intent
mark_as_good_route
```

Implicit:

```text
clicked_run_research
ignored_run_research_card
edited_ticker
sent_clarification
repeated_same_request
task_completed
task_failed
opened_evidence
exported_report
```

### Reward Sketch

Early reward can be simple:

```text
+1 user clicked Run Research after route suggestion
+1 task completed successfully
+1 user gave thumbs up
+1 user opened evidence or exported report
-1 user corrected intent
-1 user cancelled task
-1 task failed
-1 repeated clarification loop
```

This should start as analytics, not as an online optimizer.

### Contextual Bandit Before Full RL

The first useful learning algorithm is more likely to be contextual bandit than full RL.

Context:

```text
intent
confidence
missing_fields
message length
has_ticker
has_filing_type
session history summary
available skills
```

Actions:

```text
stream_chat
ask_clarification
show_run_research_card
auto_create_task
show_unsupported
```

Reward:

```text
clicks, feedback, task success, reduced clarification, report export
```

This is easier to reason about than full multi-step RL and fits the current product better.

### Full RL Criteria

Only consider full RL after:

- Intent taxonomy is stable.
- Task workflows are stable.
- There is enough logged interaction data.
- Reward can be measured without guessing.
- Offline replay/evaluation exists.
- Bad policy actions are bounded by confirmation gates.

Until then, deterministic policy plus logged feedback is the safer engineering path.

## Implementation Plan

Current implementation status:

- `autofin/intent_router.py` defines `RoutedIntent`, `DeterministicIntentRouter`, and `LLMIntentRouter`.
- `LLMIntentRouter` does not silently fall back when a configured model fails. It returns `intent_routing_failed` so the UI can show the real routing problem.
- `autofin/policy.py` defines `PolicyEngine`, `PolicyDecision`, and local JSONL policy logging.
- `/api/chat` returns routing and policy metadata without auto-running research.
- `/api/chat/stream` emits `chat-meta`, then streams the assistant response.
- `/api/research/run` creates the SEC filing research task after explicit user confirmation.
- The Web UI renders an intent chip and a `Run Research` action card for executable SEC filing requests.

### Step 1: Add RoutedIntent

Add:

```text
autofin/intent_router.py
```

Classes:

```text
RoutedIntent
LLMIntentRouter
DeterministicIntentRouter
IntentRouteResult
```

### Step 2: Replace ResearchIntent Gradually

Keep compatibility with current `ResearchIntent`, but make `/api/chat` use `RoutedIntent`.

### Step 3: Add UI Intent Chip

Expose routing metadata from `/api/chat` and `/api/chat/stream`.

### Step 4: Add Run Research Action Card

Do not auto-run research from ordinary `Send`.

Add explicit:

```text
POST /api/research/preview
POST /api/research/run
```

or add:

```text
POST /api/chat/actions/run-research
```

### Step 5: Add Evaluation Fixture

Add JSONL cases and deterministic tests.

### Step 6: Add PolicyEngine and Policy Log

Add:

```text
autofin/policy.py
```

Classes:

```text
PolicyDecision
PolicyEngine
PolicyLogger
```

First implementation should be deterministic. It should log decisions but not learn online.

### Step 7: Add Feedback Collection

Add UI events:

```text
thumbs up/down
wrong intent
run research clicked
task completed
evidence opened
```

Write them into a local JSONL or SQLite table for later evaluation.

## Open Questions

- Should `Send` ever auto-run research, or should research always require `Run Research`?
- Should `research_sec_filing` with high confidence auto-create a task but not execute until confirmed?
- Should intent routing use conversation history or only the latest message?
- How should company names without ticker be resolved?
- Should settings intent be allowed to change config through chat, or only guide users to the panel?
- Which feedback signals should count as positive reward?
- Should policy learning be per-user local only, or exportable as anonymized evaluation data?

## Recommendation

Use the LLM as the router, but keep execution policy deterministic.

For the next coding step:

1. Add `RoutedIntent` and `LLMIntentRouter`.
2. Add explicit routing failure states instead of silent deterministic fallback.
3. Add deterministic `PolicyEngine`.
4. Return routing and policy metadata from chat endpoints.
5. Add an intent chip to the UI.
6. Add a `Run Research` button so task execution is explicit.
7. Start logging policy decisions and feedback before attempting any learning.
