# AutoFinResearchAgent 功能与特色研究

## 产品定位

AutoFinResearchAgent 的定位不是普通金融聊天机器人，而是一个本地优先、可审计、可恢复的金融研究 agent 工作台。

核心目标：

```text
自然语言输入
  -> LLM 意图识别
  -> 确定性执行策略
  -> LangGraph 研究任务
  -> Skill 调用真实数据源
  -> Evidence + Trace + Report
  -> Session Memory 支持多轮跟进
```

这个项目应该围绕“研究工作流”构建，而不是只围绕“问答回复”构建。

## 目标用户

### 个人投资研究者

需要快速查看公司 10-K / 10-Q 的业务、风险、管理层讨论和财务披露，并希望知道结论来自哪里。

关键需求：

- 用自然语言发起研究
- 看到原始 SEC filing 来源
- 快速获得结构化摘要
- 能继续追问同一个公司或同一份 filing

### 金融分析师 / 研究助理

需要把重复的资料收集、filing 检索、段落抽取、初步 memo 整理自动化，但不希望模型无依据地编造结论。

关键需求：

- 可追溯 evidence
- 可复核 trace
- 可导出的研究 memo
- 多轮会话和任务状态可恢复

### Agent 应用开发者

需要一个以 LangChain + LangGraph 为核心的金融 agent 参考架构。

关键需求：

- 清晰的 intent routing
- skill abstraction
- deterministic policy boundary
- session memory
- local-first runtime

## 已实现功能

### 1. Chat-first 研究入口

用户可以像使用 Codex-style agent app 一样输入自然语言：

```text
帮我分析 PLTR 最近的 10-K
重点看 risk factors 和 cash flow
继续刚才那个公司
```

系统不是把每句话都硬转成任务，而是先经过 LLM intent routing。

已支持的入口能力：

- 普通对话
- 应用能力解释
- 模型配置提示
- SEC filing 研究识别
- 研究任务确认卡

### 2. LLM 意图识别 + 确定性策略层

LLM 负责分类和字段抽取：

```json
{
  "intent": "research_sec_filing",
  "ticker": "PLTR",
  "filing_type": "10-K",
  "focus": ["risk factors", "cash flow"],
  "needs_confirmation": true
}
```

PolicyEngine 负责决定下一步：

- 普通对话：直接流式回复
- SEC 研究字段完整：展示 Run Research 卡片
- 缺少 ticker：要求澄清
- 未实现能力：明确说明限制
- 路由失败：显示显式错误

这条边界很重要：LLM 不直接执行工具，不直接修改状态。

### 3. LangGraph 研究任务执行

当前任务流：

```text
start_trace
  -> select_skill
  -> check_permissions
  -> execute_skill
  -> write_result_trace
```

特色：

- 每一步都有 trace
- skill 先声明权限
- workflow 可以扩展 checkpoint、resume、human-in-the-loop
- 后续可以根据 intent 分支到不同研究路径

### 4. SEC Filing 自动分析 v1

`sec_filing_analysis` 已经从 metadata retrieval 升级为正文分析。

当前流程：

```text
ticker
  -> SEC company ticker map
  -> latest 10-K / 10-Q metadata
  -> filing document HTML
  -> text extraction
  -> section detection
  -> evidence-backed highlights
  -> structured report
```

已抽取区域：

- Business
- Risk Factors
- MD&A
- Financial Statements

输出结构：

```text
result.data.summary
result.data.analysis.sections
result.data.analysis.report
result.evidence[]
```

这个版本先生成 extractive analysis，并在 Web runtime 中接入可选的 LLM evidence-grounded memo synthesis。模型可用时，memo 必须引用 evidence id；模型不可用或输出无效时，系统降级为 extractive memo，不让研究任务失败。

### 5. Evidence-backed Report 面板

UI 右侧已经有独立 Report 面板。

当前展示：

- Executive Summary
- Key Observations
- Risk Watchlist
- Limitations
- Markdown memo artifact preview
- 可展开 Evidence excerpt
- Evidence citation id
- Report / chat citation 点击跳转到 Evidence
- Activity 阶段化 Timeline
- 原始 JSON 调试视图

这个设计让用户先看可读报告，再回到 evidence 和 JSON 复核。

### 6. 研究任务可追问

完成研究任务后，用户可以在同一个 session 里继续问：

```text
这个公司的主要风险是什么？
解释 E3
总结成三点
这个结论来自哪里？
```

系统会把 active task 的 report、risk watchlist 和 evidence 摘要注入 chat responder 上下文，并通过 `research_qa` 意图回答。回答应优先引用 `[E1]` 这类 evidence id；如果当前报告证据不足，应明确说明。

### 7. Session + Memory

系统支持 session，而不是一次性请求。

Session 保存：

- messages
- title
- memory
- active_task_id
- task_summaries

Memory 保存：

- last_intent
- ticker
- filing_type
- focus
- pending_action
- active_task_id

因此可以支持：

```text
帮我分析 AAPL 10-K
继续刚才那个，重点看现金流
整理成 memo
```

当前 memory 是短期、可见、可序列化的，不是隐藏长期个性化记忆。

### 8. 本地持久化

当前本地持久化：

```text
.autofin/config.json
.autofin/secrets.json
.autofin/sessions/
.autofin/sessions/transcripts/
.autofin/tasks/
.autofin/traces/
.autofin/artifacts/
```

解决的问题：

- 服务重启后模型配置不丢
- session 不丢
- active task result 不丢
- trace 和 evidence 可复核
- Markdown memo artifact 可导出和复用

### 9. Model API 配置

UI 左侧支持配置：

- provider
- model
- base_url
- api_key
- temperature

API key 不会明文返回，只显示脱敏状态。

## 项目特色

### 特色一：不是聊天机器人，而是研究工作台

普通聊天机器人侧重“回答”。本项目侧重“研究过程”。

关键差异：

| 维度 | 普通金融聊天 | AutoFinResearchAgent |
| --- | --- | --- |
| 输入 | 自然语言 | 自然语言 |
| 执行 | 模型直接回答 | intent -> policy -> task |
| 证据 | 常常不明确 | evidence 显式展示 |
| 状态 | 单轮为主 | session + memory |
| 任务 | 不可恢复 | task persistence |
| 审计 | 难复核 | trace + source URL |

### 特色二：LLM 只负责适合它的部分

LLM 擅长：

- 理解用户意图
- 抽取 ticker / filing_type / focus
- 做自然语言总结

LLM 不应该直接负责：

- 是否执行任务
- 是否修改状态
- 是否绕过确认
- 是否凭空生成金融事实

当前架构把这些职责拆开了。

### 特色三：Evidence-first

研究任务的输出必须能回答：

```text
这个结论来自哪里？
我能不能点回原文？
是否能看到系统做了什么？
```

因此 Report、Evidence、Trace 是同等重要的界面元素。

### 特色四：本地优先

本地优先不是“不联网”，而是：

- 用户配置保存在本地
- session 和 task 保存在本地
- 研究过程可本地复盘
- 后续可以接本地模型、本地向量库、本地 artifact

这对金融研究很重要，因为研究笔记、watchlist、偏好和 API key 都不应该被随意外发。

### 特色五：可扩展 skill system

当前只有 `sec_filing_analysis`，但架构已经为更多 skill 留了位置。

候选 skills：

- `market_data_analysis`
- `financial_statement_parser`
- `earnings_call_analysis`
- `company_news_research`
- `peer_comparison`
- `valuation_snapshot`
- `memo_writer`
- `portfolio_monitor`

## 当前短板

### 1. SEC memo synthesis 仍然是第一版

当前已经可以在配置模型后基于 evidence 生成 memo，并校验引用是否真实存在。UI 已支持 citation 跳转和 Markdown artifact 预览。仍然缺少更细粒度的引用覆盖率校验、报告格式控制和导出操作。

缺口：

- citation 覆盖率校验
- 多段 evidence 合并和去重
- 中英文报告风格控制
- 下载、复制、归档等导出按钮

### 2. 财务表解析还不够

当前可以看到 financial statement 相关片段，但还没有把 XBRL / 表格转成结构化指标。

缺口：

- revenue
- gross margin
- operating income
- net income
- operating cash flow
- free cash flow
- cash / debt
- YoY / QoQ comparison

### 3. LangGraph runtime 还没有 checkpoint/resume

任务结果已经持久化，但 workflow 本身还没有真正 checkpoint。

后续应加入：

- task pause / resume
- retry failed node
- checkpoint state
- human approval node

### 4. UI 还不是最终工作台形态

当前 static UI 适合快速验证 API，但长期可能需要 React/Tauri。

需要增强：

- task history filter
- active task workspace
- report export controls
- compare view
- richer active-task switching

## 推荐产品主线

### 主线 A：SEC Filing Research Agent

这是最应该先打磨的主线。

目标体验：

```text
用户：分析 PLTR 最近 10-K，重点看增长、商业模式和风险
系统：
1. 识别 PLTR / 10-K / focus
2. 用户确认 Run Research
3. 下载 filing
4. 抽取 Business / Risk / MD&A / Financials
5. 解析关键财务指标
6. 生成 evidence-cited memo
7. 支持继续追问
```

为什么优先：

- 数据源稳定
- evidence 清楚
- 和金融研究强相关
- 容易形成可展示 demo

### 主线 B：Multi-turn Research Workspace

目标体验：

```text
分析 AAPL
再分析 MSFT
比较一下两者风险
把刚才结果整理成中文 memo
```

需要能力：

- session memory
- task summaries
- source_task_id resolution
- compare workflow
- report writer workflow

### 主线 C：Local-first Research Memory

目标体验：

```text
以后分析 SaaS 公司都重点看 NRR、RPO、FCF margin
记住我的报告格式
下次生成同样结构
```

需要能力：

- explicit memory settings
- preference memory
- project-level memory
- memory inspection / delete

## 推荐开发路线

### Phase 1：把 SEC Filing 研究做完整

优先级最高。

任务：

1. report schema 固定化
2. citation 覆盖率校验
3. memo 风格模板
4. export controls and copy actions
5. evidence 去重和引用覆盖率报告

完成标准：

- 用户输入一个 ticker 后，可以得到可读、可复核的研究 memo
- 每个重要结论都能回到 filing excerpt

### Phase 2：结构化财务指标

任务：

1. SEC XBRL companyfacts API
2. 常用指标抽取
3. 年度/季度趋势
4. 简单质量检查
5. 表格 UI

完成标准：

- Report 里不仅有文字摘要，还有关键数字
- 支持 YoY / QoQ

### Phase 3：多任务、多轮报告

任务：

1. `write_report` intent 实现
2. `compare_companies` workflow
3. active task selection
4. task artifact store
5. report versioning

完成标准：

- 用户可以把多个任务结果整理成一份 memo
- 可以比较两个或多个公司

### Phase 4：Runtime 可靠性

任务：

1. SQLite 替代 JSON 文件任务存储
2. LangGraph checkpoint
3. task retry
4. cancellation
5. background worker queue

完成标准：

- 长任务可以可靠恢复
- UI 能暂停、取消、重跑任务

### Phase 5：桌面应用化

任务：

1. React UI
2. Tauri wrapper
3. local file/artifact browser
4. OS keychain secret storage
5. local model option

完成标准：

- 像一个真正的桌面研究工作台
- 能管理本地研究资料、报告和配置

## 建议的近期任务

按照收益和依赖关系排序：

1. 增加 SEC companyfacts 财务指标 skill
2. 增加 Report 导出按钮和 copy actions
3. 实现 `write_report` intent
4. 增加多任务比较 workflow
5. 设计 task artifact store
6. 增加 UI 的 active task history
7. 增加 memo 风格模板和中英文切换
8. 加强 citation 覆盖率和 evidence 去重

## 产品原则

1. 先证据，后结论。
2. LLM 负责表达和归纳，不负责凭空创造事实。
3. 所有自动执行都经过 policy boundary。
4. 所有重要结果都可复核、可恢复、可导出。
5. Memory 必须可见、可删除、可解释。
6. 默认本地优先，外部调用显式配置。
