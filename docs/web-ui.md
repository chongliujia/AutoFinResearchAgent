# Web UI Development Notes

## 启动方式

使用 conda 环境 `rag`：

```bash
source /Users/jiachongliu/anaconda3/etc/profile.d/conda.sh
conda activate rag
python -m autofin.cli serve --port 8097
```

打开：

```text
http://127.0.0.1:8097
```

## 当前页面结构

```text
左侧：Sessions + Skills + Model API
中间：Chat log + Composer
右侧：Current task progress + tabbed inspector
      Report | Evidence | Activity | Memory | JSON
```

这个布局刻意接近本地 agent app：用户主要在中间对话，系统状态和证据放到右侧 inspector。

金融研究 agent 的关键交互对象是：

- session
- task
- skill
- permission
- trace
- evidence
- artifact

Chat 是主要入口，但不是唯一信息载体。金融研究 agent 需要同时展示执行状态、证据和产物。

当前 Chat 入口的设计是：

```text
user message
  ↓
intent routing
  ↓
general reply, research follow-up QA, or structured task
  ↓
LangGraph workflow
  ↓
inline events + task progress + report/evidence/artifacts
```

对于普通对话，后端会直接返回 assistant message，不创建任务。对于研究任务，解析器会从文本里抽取：

- ticker
- filing type
- objective
- focus

如果 Model API 已配置，后端会使用 LangChain structured output；否则使用 deterministic fallback，让本地 UI 在没有模型 key 时仍然可用。

## UI 原则

- 中间区域优先服务对话，不放大表单
- 输入框固定在底部，形成持续 session 的感觉
- LangGraph 事件汇总成可读 Activity，关键 tool call 也内联进入对话流
- Skill 调用在对话流中用可折叠 tool call 卡片展示
- Report、Evidence、Activity、Memory、JSON 放在右侧 tabbed inspector
- Report 和聊天里的 citation 可以点击跳转到 Evidence
- Markdown memo artifact 可以在 Report 面板预览
- 左侧保留 sessions 和 skills，方便切换上下文
- 左侧提供 Model API 配置入口，API key 只显示脱敏状态
- 表单能力保留在 API 层，UI 不再把它作为主路径

## Model API 配置

可以通过环境变量配置：

```bash
export AUTOFIN_MODEL_PROVIDER=openai-compatible
export AUTOFIN_MODEL_NAME=
export AUTOFIN_MODEL_BASE_URL=
export AUTOFIN_MODEL_API_KEY=
export AUTOFIN_MODEL_TEMPERATURE=0.2
export AUTOFIN_SEC_USER_AGENT="AutoFinResearchAgent your-email@example.com"
```

也可以在 Web UI 左侧 `Model API` 面板中配置。UI 保存后会写入：

```text
.autofin/config.json
.autofin/secrets.json
```

`.autofin/` 已经被 gitignore。API key 不会被接口明文返回。

## Tool Call 卡片

任务执行时，后端会发出：

- `tool_call_requested`
- `tool_call_completed`

前端会把这些事件渲染成可折叠卡片。展开后可以查看：

- inputs
- permissions
- trace_id
- evidence

## API

### Health

```http
GET /api/health
```

### Skills

```http
GET /api/skills
```

### Tasks

```http
GET /api/tasks
POST /api/tasks
GET /api/tasks/{task_id}
GET /api/tasks/{task_id}/artifacts/{artifact_index}
GET /api/tasks/{task_id}/events
```

`/events` 使用 Server-Sent Events，适合流式展示 LangGraph 运行状态。

### Chat

```http
POST /api/chat
POST /api/chat/stream
POST /api/research/run
```

请求：

```json
{
  "message": "帮我分析 AAPL 最近的 10-K，重点看风险因素和现金流"
}
```

`/api/chat/stream` 会流式返回普通对话、研究追问或确认卡片。`/api/research/run` 在用户点击 Run Research 后创建结构化任务。

### Model Settings

```http
GET /api/settings/model
POST /api/settings/model
```

## 创建任务示例

```bash
curl -sS http://127.0.0.1:8097/api/tasks \
  -H 'Content-Type: application/json' \
  -d '{"ticker":"AAPL","filing_type":"10-K","objective":"Analyze SEC filing"}'
```

## 下一步 UI 能力

1. 增加 permission approval panel
2. 增加 trace event 详情抽屉
3. 增加 report export / copy actions
4. 增加 artifact 文件列表和版本管理
5. 增加 watchlist 和 scheduled research
6. 迁移到 React + typed API client
