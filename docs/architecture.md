# AutoFinResearchAgent Architecture

## 目标定位

AutoFinResearchAgent 的核心目标不是做一个普通聊天机器人，而是做一个可审计、可恢复、可扩展的金融研究工作台。

当前架构分成四层：

```text
Web UI
  ↓
FastAPI service
  ↓
LangGraph research workflow
  ↓
Skill runtime + sandbox boundary
```

## LangChain 和 LangGraph 的分工

### LangGraph

LangGraph 用来表达长期任务的状态流转。

当前 MVP 的 workflow 是：

```text
start_trace
  ↓
select_skill
  ↓
check_permissions
  ↓
execute_skill
  ↓
write_result_trace
```

对应代码在：

```text
autofin/runtime/orchestrator.py
```

后续适合加入：

- checkpoint，用于任务恢复
- human-in-the-loop，用于权限确认和关键判断
- conditional edges，用于根据任务类型选择不同研究路径
- memory，用于维护长期 research session

### LangChain

LangChain 用来适配工具、模型和结构化输出。

当前 `Skill` 可以转换成 LangChain `StructuredTool`：

```text
autofin/skills/base.py
```

Chat intent routing 现在分成两层：

```text
autofin/intent_router.py
autofin/policy.py
```

当 Model API 已配置时，`LLMIntentRouter` 用 LangChain structured output 判断用户消息属于普通对话、配置问题、SEC filing 研究、行情、新闻、报告等 intent。这里不做静默 deterministic fallback：未配置模型时返回配置提示；模型调用失败或输出格式无效时返回显式 routing error。

`PolicyEngine` 是执行边界。LLM 只负责分类和抽取字段，不直接创建任务。`research_sec_filing` 在字段完整时会返回 `show_run_research_card`，UI 需要用户点击 `Run Research` 后才会调用 `/api/research/run` 创建 LangGraph 任务。

后续可以把 skills 交给 LangChain agent 或 LangGraph node 调用。

## Session, Memory, and Agent Runtime

当前 chat flow 已经从单轮消息升级为 session-aware runtime：

```text
Web UI session_id
  |
  v
AgentRuntime
  |
  +-- SessionStore / SessionMemory
  +-- LLMIntentRouter with session context
  +-- PolicyEngine
  +-- ChatResponder
  +-- TaskStore / LangGraph research task
```

核心文件：

```text
autofin/session.py
autofin/memory.py
autofin/agent_runtime.py
```

`SessionStore` 维护 conversation session、message transcript 和 active task。`SessionMemory` 维护短期上下文，包括最近消息摘要、working entities、pending action 和 active task id。`AgentRuntime` 把 session context 注入 LLM intent routing 和普通聊天回复。

更完整的设计见：

```text
docs/session-memory-runtime.md
```

## Skill 设计

每个 skill 是一个可声明、可测试、可复用的能力单元。

当前 skill 必须具备：

- `name`
- `description`
- `permissions`
- `run(inputs)`

示例：

```text
autofin/skills/sec_filing.py
```

当前 `sec_filing_analysis` 已经接入 SEC metadata、filing HTML 下载和抽取式正文分析：

```text
autofin/data/sec_client.py
autofin/skills/sec_filing.py
```

当前流程会通过 SEC company ticker map 和 submissions JSON 获取最近 10-K / 10-Q 的 filing metadata、accession number、primary document 和 SEC source URL，然后下载 filing document HTML，抽取正文文本，并为这些区域生成 evidence-backed highlights：

- Business
- Risk Factors
- MD&A
- Financial Statements

分析结果同时包含 `analysis.report`，用于 UI 右侧的 Report panel。默认 skill 可以生成确定性的 extractive memo；Web runtime 会注入 `LangChainEvidenceMemoSynthesizer`，在 Model API 已配置时基于 evidence ids 生成 LLM evidence-grounded memo。模型不可用或输出无效时会降级为 extractive memo，不让研究任务失败。系统会校验 memo citation 是否指向真实 evidence id，并把 Markdown memo artifact 写入 `.autofin/artifacts/`。UI 已支持 Report / Evidence citation 联动、Markdown artifact 预览、任务阶段可视化，以及基于 active task 的 evidence-grounded follow-up QA。下一步适合加入结构化财务表解析和多任务比较。

## Sandbox 设计

当前 `SandboxExecutor` 还是 in-process 执行，只负责建立代码边界。

下一阶段应该升级为：

- subprocess 执行
- timeout
- 临时工作目录
- stdout/stderr 大小限制
- 网络白名单
- 文件访问范围限制

对应代码在：

```text
autofin/sandbox/executor.py
```

## Web UI 设计

当前先使用 FastAPI 内置静态 UI，而不是立刻引入 React 构建链。

这样做的原因：

- 本地开发简单
- API 边界先稳定
- 后续迁移 React/Tauri 不需要重写后端
- 更快验证 agent workflow 的交互形态

Web API 入口：

```text
autofin/web/app.py
```

任务状态存储：

```text
autofin/web/task_store.py
```

静态 UI：

```text
autofin/web/static/
```

## Model API 配置

模型配置集中在：

```text
autofin/config.py
```

后端启动时会读取这些环境变量：

```text
AUTOFIN_MODEL_PROVIDER
AUTOFIN_MODEL_NAME
AUTOFIN_MODEL_BASE_URL
AUTOFIN_MODEL_API_KEY
AUTOFIN_MODEL_TEMPERATURE
AUTOFIN_SEC_USER_AGENT
```

Web UI 左侧也提供 `Model API` 面板。通过 UI 提交的配置会保存到本地：

```text
.autofin/config.json
.autofin/secrets.json
```

`config.json` 保存 provider、model、base_url 和 temperature；`secrets.json` 保存 API key。`.autofin/` 已经被 gitignore。API key 不会被接口明文返回，只会返回是否已配置以及脱敏预览。

后续如果要加强安全性，可以把 `secrets.json` 替换为 macOS Keychain 或其他 secret store。

`AUTOFIN_SEC_USER_AGENT` 用于 SEC EDGAR 请求。实际使用时应设置成包含项目名和联系方式的值。

### Chat 入口

当前 UI 支持类似 Codex app 的对话入口，但执行层仍然是结构化任务。

```text
Chat message
  ↓
intent routing
  ↓
conversation reply, research follow-up QA, or structured research task
  ↓
LangGraph execution
  ↓
task progress + report + evidence + artifact
```

这样做的原因是：用户用自然语言表达目标，但系统需要保留权限检查、trace、evidence 和可恢复执行。

解析器代码在：

```text
autofin/intent.py
```

更完整的 intent routing 设计见：

```text
docs/intent-routing.md
```

## 推荐演进路线

1. SEC filing skill 接入真实 SEC API
2. TaskStore 从内存迁移到 SQLite
3. SEC companyfacts / XBRL 财务指标解析
4. LangGraph 加 checkpoint 和 resume
5. SandboxExecutor 改为 subprocess/container
6. 前端迁移到 React
7. 使用 Tauri 包成本地桌面应用
