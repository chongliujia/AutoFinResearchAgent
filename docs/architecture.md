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

Chat intent routing 也已经接入 LangChain structured output：

```text
autofin/intent.py
```

当 Model API 已配置时，`/api/chat` 会优先用模型判断用户消息是普通对话还是研究任务，并把研究任务解析成结构化 intent；未配置或调用失败时，自动回退到 deterministic parser。

后续可以把 skills 交给 LangChain agent 或 LangGraph node 调用。

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

当前 `sec_filing_analysis` 已经接入 SEC metadata：

```text
autofin/data/sec_client.py
```

第一版会通过 SEC company ticker map 和 submissions JSON 获取最近 10-K / 10-Q 的 filing metadata、accession number、primary document 和 SEC source URL。正文下载、section extraction 和总结会在后续迭代中加入。

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
conversation reply or structured research task
  ↓
LangGraph execution
  ↓
timeline + evidence + artifact
```

这样做的原因是：用户用自然语言表达目标，但系统需要保留权限检查、trace、evidence 和可恢复执行。

解析器代码在：

```text
autofin/intent.py
```

## 推荐演进路线

1. SEC filing skill 接入真实 SEC API
2. TaskStore 从内存迁移到 SQLite
3. Web UI 增加 artifact 预览
4. LangGraph 加 checkpoint 和 resume
5. SandboxExecutor 改为 subprocess/container
6. 前端迁移到 React
7. 使用 Tauri 包成本地桌面应用
