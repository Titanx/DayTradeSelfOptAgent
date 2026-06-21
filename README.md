# AStockAgent

基于数据和舆论监控的 A 股量化交易多智能体系统。

## 参考项目

本项目架构设计参考了以下两个优秀项目：

- **[TradingAgents](https://github.com/TauricResearch/TradingAgents)** — 多智能体交易框架，借鉴了其 Analyst→Researcher→Trader→Risk Manager 的多 Agent 协作范式，以及多空辩论（Bull/Bear Debate）和风险讨论（Aggressive/Conservative/Neutral）的设计思路。
- **[Agent-Reach](https://github.com/your-repo/Agent-Reach)** — 多平台信息获取框架，借鉴了其多渠道舆论监控和数据聚合的设计模式，项目中舆论模块保留了对其 Channel 接口的可选兼容。

## 架构概览

```
用户输入（股票代码）
       │
       ▼
┌─────────────────────────────────────┐
│         第一阶段：信息收集            │
│  ┌──────────┐  ┌──────────┐         │
│  │ 基本面分析 │  │ 技术面分析 │         │
│  └──────────┘  └──────────┘         │
│  ┌──────────┐  ┌──────────┐         │
│  │ 舆论情绪   │  │ 政策分析   │         │
│  └──────────┘  └──────────┘         │
└─────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────┐
│         第二阶段：多空辩论            │
│     Bull Researcher ⟷ Bear Researcher│
│              ↓                       │
│        Research Manager 汇总          │
└─────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────┐
│         第三阶段：交易决策            │
│         Trader（A股 T+1 规则）        │
└─────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────┐
│         第四阶段：风控讨论            │
│  Aggressive ⟷ Conservative ⟷ Neutral │
│              ↓                       │
│       Portfolio Manager 最终评级      │
└─────────────────────────────────────┘
       │
       ▼
  最终输出：评级 + 行动计划 + 置信度
```

## 快速开始

### 环境要求

- Python 3.10+
- conda（推荐）

### 安装

```bash
# 创建环境
conda create -n stocka python=3.12
conda activate stocka

# 安装依赖
pip install -r requirements.txt
```

### 配置

复制环境变量模板并填入 API Key：

```bash
cp .env.example .env
```

编辑 `.env`，至少配置：

```env
DEEPSEEK_API_KEY=your_deepseek_api_key
```

支持的大模型：DeepSeek（默认）、OpenAI、Qwen、Anthropic、Google Gemini、Ollama。

### 运行

**单只股票分析：**

```bash
python sample_analyze.py
```

**批量分析（25 只股票，5 个行业 × 5 只）：**

```bash
python batchanalyze.py
```

**命令行入口：**

```bash
python main.py --code 600519 --date 2026-06-20
```

## 项目结构

```
AStockAgent/
├── agents/
│   ├── analysts/         # 4 个分析师 Agent
│   │   ├── fundamental_analyst.py   # 基本面
│   │   ├── technical_analyst.py     # 技术面
│   │   ├── sentiment_analyst.py     # 舆论情绪
│   │   └── policy_analyst.py        # 政策面
│   ├── researchers/      # 多空研究员
│   │   ├── bull_researcher.py       # 多方 + 研究管理
│   │   └── bear_researcher.py       # 空方
│   ├── trader.py         # 交易员（A股 T+1）
│   ├── risk_mgmt.py      # 风控讨论 + 组合管理
│   ├── schemas.py        # Pydantic 数据模型
│   └── utils/            # 工具函数 + 记忆系统
├── dataflows/
│   ├── interface.py      # 统一数据接口
│   └── akshare_adapter.py # AKShare 适配器（多源回退）
├── graph/
│   ├── trading_graph.py  # LangGraph 主图
│   ├── setup.py          # 图构建配置
│   └── conditional_logic.py # 条件路由
├── opinion/
│   ├── xueqiu_monitor.py # 雪球监控
│   └── sentiment_aggregator.py # 情绪聚合
├── config/
│   └── default_config.py # 项目配置
├── main.py               # CLI 入口
├── batchanalyze.py       # 批量分析脚本
├── sample_analyze.py     # 单股分析示例
└── test_akshare.py       # 数据源连通性测试
```

## 功能特点

- **多智能体协作** — 4个分析师 + 多空辩论 + 3方风控讨论，模拟真实投研流程
- **多源数据融合** — AKShare + 东方财富 + 新浪 + 腾讯 + 同花顺，自动回退
- **舆论监控** — 雪球热门帖子、微博情绪、财经新闻聚合
- **差异化评级** — Underweight / Hold / Overweight + 置信度
- **T+1 交易规则** — 完全符合 A 股交易制度
- **非交易日处理** — 自动回退到最近交易日数据
- **结果持久化** — 按股票代码分类存储，含思考过程 Markdown

## License

MIT
