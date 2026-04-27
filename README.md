# AutoFinResearchAgent

### 核心思路：

Agent Runtime 负责“想和调度”，Skills 负责“会做什么”，Sandbox 负责“安全执行”。

架构可以这样设计：

```
Financial Agent Runtime
├── Agent Orchestrator
├── Skill Registry
│   ├── sec_filing_skill
│   ├── market_data_skill
│   ├── news_monitor_skill
│   ├── financial_analysis_skill
│   ├── report_writing_skill
│   └── chart_generation_skill
├── Sandbox Executor
│   ├── Python Sandbox
│   ├── SQL Sandbox
│   ├── Browser / HTTP Sandbox
│   └── File Sandbox
├── Memory / State Store
├── Scheduler
├── Trace / Audit Log
└── Notification

```

Skills 怎么设计

每个 Skill 都应该是可声明、可测试、可复用的能力单元。

例如：

```
name: sec_filing_analysis
description: Analyze SEC 10-K / 10-Q filings
inputs:
  ticker: string
  filing_type: string
outputs:
  filing_summary: object
  evidence: list
permissions:
  network:
    - sec.gov
  filesystem:
    - read
    - write_temp
runtime:
  sandbox: python

```

Sandbox 怎么设计

Sandbox 负责隔离风险。

金融 Agent 会执行：

Python 分析代码
下载 SEC 文件
生成图表
读取本地文件
访问外部 API

这些都不能裸跑。

Sandbox 应该限制：

```
网络访问白名单
文件系统访问范围
CPU / 内存 / 时间限制
API key 权限
禁止危险系统调用
输出大小限制

```

最推荐的执行模型:

```
Agent decides task
↓
Runtime selects skill
↓
Skill declares required permissions
↓
Sandbox creates isolated environment
↓
Skill executes
↓
Output validated by schema
↓
Trace written to audit log
```

项目真正的亮点

可以把项目定位成：

```
A skill-based, sandboxed runtime for long-running financial research agents.
```
