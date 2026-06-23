# DayTradeSelfOptAgent

基于数据和舆论监控的 A 股一日游策略多智能体系统，集成 SkillOpt 自我优化闭环。

> ⚠️ **免责声明**: 本项目仅供学习研究使用，所有分析结果均不构成任何投资建议。股市有风险，投资需谨慎。

## 运行环境与成本

| 项目 | 说明 |
|------|------|
| **推理模型** | DeepSeek-V4（所有 Agent prompt 均针对 DS-V4 特性优化） |
| **单股成本** | ≈ 0.3 元（每只股票完整分析链路约 15-20 次 LLM 调用） |
| **25 股批量成本** | ≈ 7.5 元（含 4 分析师 + 多空辩论 + 交易员 + 3 方风控讨论） |
| **月成本估算** | ≈ 150 元（20 个交易日 × 25 股） |

> 成本随 DeepSeek 官方定价波动，以上为 2026 年 6 月参考值。每次调用平均约 2-3 万 token（含上下文数据 + prompt + 输出），V4 的 JSON Mode 结构化输出可减少约 30% 的 token 消耗。

## 策略说明：一日游 (One-Day Swing)

本系统实现的是「一日游」超短线策略，交易节奏为 2 天周期：

```
Day 0 (收盘后)  →  多 Agent 分析评估  →  决定 Day 1 是否买入
Day 1 (次日)    →  开盘买入（如果决策为 Buy/Overweight）
Day 2 (第三日)  →  收盘前强制平仓，无论盈亏
```

**硬约束**：
- 只做多，不做空（策略无卖单）
- 单只股票仓位 ≤ 30%
- Day 2 必须卖出，持有仅 1 个交易日
- Day1 涨幅预期 ≥ 1%（扣除印花税+佣金约 0.11% 后净利约 0.89%）
- 流动性过滤：日成交额 ≥ 1 亿，禁止 ST 股票，回避跌停/停牌风险

## 策略设计理念：为什么是一日游

> 一日游不是追求单次收益最大化，而是**追求反馈样本积累速度最大化**。
> 一天 25 个样本、月 500 个样本（相当长期策略的一年半），每 2 天就能验证一条 prompt 好不好。
> 基于这个反馈密度，用 [SkillOpt](https://github.com/microsoft/SkillOpt) 框架自动优化 Agent 的 Prompt 文档（`skills/*.skill.md`），
> 让命中率/踏空率/误判率在闭环迭代中持续收敛。详见 [docs/one_day_swing_strategy.md](docs/one_day_swing_strategy.md)。

## 参考项目

本项目架构设计参考了以下三个优秀项目：

- **[TradingAgents](https://github.com/TauricResearch/TradingAgents)** — 多智能体交易框架，借鉴了其 Analyst→Researcher→Trader→Risk Manager 的多 Agent 协作范式，以及多空辩论（Bull/Bear Debate）和风险讨论（Aggressive/Conservative/Neutral）的设计思路。
- **[Agent-Reach](https://github.com/your-repo/Agent-Reach)** — 多平台信息获取框架，借鉴了其多渠道舆论监控和数据聚合的设计模式。
- **[SkillOpt](https://github.com/microsoft/SkillOpt)** — 微软开源的 Agent Skill 优化框架（论文 arXiv:2605.23904）。将深度学习训练方法论（前向/反向传播、有界编辑、验证门控、慢速更新）移植到文本空间，把 Agent Prompt 当作可训练参数来优化。本项目 `skills/` 目录的 Markdown 解耦架构直接对齐 SkillOpt 的 skill-as-trainable-state 范式。

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
│         第三阶段：一日游交易决策        │
│         Trader（Day1买入 Day2强制平仓）  │
└─────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────┐
│         第四阶段：风控讨论            │
│  Aggressive ⟷ Conservative ⟷ Neutral │
│              ↓                       │
│       Portfolio Manager 最终决策      │
│    Buy=Day1买入 / Hold=不参与        │
└─────────────────────────────────────┘
       │
       ▼
  最终输出：Buy/Hold 决策 + 信心度 + 辩论轨迹
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

**单只股票测试：**

```bash
python tests/test_one_stock.py
```

**10 只股票快速测试：**

```bash
python tests/test_10stocks.py
```

**25 只股票批量分析（5 板块 × 5 只）：**

```bash
python batchanalyze.py
```

**命令行入口：**

```bash
python main.py --code 600519 --date 2026-06-20
```

**生成每日分析报告：**

```bash
python scripts/generate_daily_report.py
# 输出: data/{date}_daily_report.md
```

**回测验证：**

```bash
# 多日批量回测 (日汇总 + 总准确率)
python scripts/backtest_multiday.py

# 单日回测 (预测 vs 次日实盘)
python scripts/backtest_day.py

# 查看当前批次进度
python scripts/_progress.py
```

## 项目结构

```
DayTradeSelfOptAgent/
├── skills/                         # SkillOpt 管理的 Agent Prompt (可编辑 Markdown)
│   ├── bull_researcher.skill.md
│   ├── bear_researcher.skill.md
│   ├── research_manager.skill.md
│   ├── trader.skill.md
│   ├── aggressive_risk.skill.md
│   ├── conservative_risk.skill.md
│   ├── neutral_risk.skill.md
│   └── portfolio_manager.skill.md
├── agents/
│   ├── analysts/             # 4 个分析师 Agent
│   │   ├── fundamental_analyst.py   # 基本面 (财务指标/估值)
│   │   ├── technical_analyst.py     # 技术面 (OHLCV/MA/量价)
│   │   ├── sentiment_analyst.py     # 舆论情绪 (雪球/新闻/微博)
│   │   └── policy_analyst.py        # 政策面 (板块/北向/情绪)
│   ├── researchers/          # 多空研究员
│   │   └── bull_researcher.py       # 多方+空方+研究管理三位一体
│   ├── risk_mgmt.py          # 风控讨论 + 投资经理终决 (一日游决策)
│   ├── trader.py             # 一日游交易员（Day1买入 Day2平仓）
│   ├── schemas.py            # Pydantic 数据模型 (一日游策略专用)
│   └── utils/
│       ├── agent_utils.py    # 工具函数 (行情/财务/舆论/流动性)
│       ├── md_utils.py       # Markdown 渲染 (to_markdown)
│       └── memory.py         # 交易记忆系统
├── dataflows/
│   ├── interface.py          # 统一数据路由 (route_to_vendor)
│   ├── akshare_adapter.py    # AKShare 适配器 (15+ API，三级回退)
│   └── market_cache.py       # 多级缓存系统 (内存→磁盘，MD+JSON 双写)
├── graph/
│   ├── trading_graph.py      # LangGraph 主图 + 结果保存 + 辩论轨迹
│   ├── setup.py              # 图构建配置 + AgentState 类型定义
│   └── conditional_logic.py  # 条件路由
├── opinion/
│   ├── xueqiu_monitor.py     # 雪球监控 (行情/帖子/搜索)
│   └── sentiment_aggregator.py # 多源情绪聚合
├── config/
│   └── default_config.py     # 项目配置
├── docs/
│   └── one_day_swing_strategy.md  # 一日游 + Agent OPT 策略文档
├── scripts/
│   ├── generate_daily_report.py  # 生成每日分析汇总 MD
│   ├── backtest_day.py           # 单日回测 (预测 vs 实盘)
│   ├── backtest_multiday.py      # 多日批量回测 (汇总统计)
│   ├── backfill_dates.py         # 历史日期补跑 (填充样本)
│   ├── _progress.py              # 当前批次进度查看
│   ├── summary.py                # 批量结果快速摘要
│   ├── verify_sector_history.py  # 板块历史数据校验
│   └── backfill_sector_history.py # 板块历史回填
├── tests/
│   ├── test_one_stock.py     # 单股快速测试
│   ├── test_5stocks.py       # 5 股一日游策略测试
│   └── test_10stocks.py      # 10 股批量测试
├── main.py                   # CLI 入口
├── batchanalyze.py           # 批量分析主脚本
├── quick_batch.py            # 精简批量脚本
├── .env.example              # 环境变量模板
└── .gitignore
```

## 数据缓存

多层 MD+JSON 双写缓存，避免重复拉取 API、加速分析。详见 [data/README.md](data/README.md)。

| 类型 | 目录 | 缓存策略 |
|------|------|---------|
| 公共数据 | `market_cache/` | 按交易日缓存，支持 30 天历史 |
| 个股数据 | `stock_cache/` | 按 symbol/trade_date 缓存 |
| 舆论数据 | `opinion_cache/` | 按 symbol/trade_date 缓存 |
| LLM 轨迹 | `agent_cache/` | 每次分析新生成，用于回溯审查 |
| 分析结果 | `results/` | 回测脚本直接读取 |
| 批量输出 | `batch_results/` | batchanalyze 产出 |

## 功能特点

- **多智能体协作** — 4 分析师 → 多空辩论 → 交易 → 3 方风控 → 经理终决，模拟投研流程
- **多源数据融合** — AKShare + 东方财富 + 新浪 + 腾讯 + 同花顺 + 雪球 + 微博，自动回退
- **MD+JSON 双写** — 缓存/结果/辩论轨迹统一 MD+JSON，人类可读 + 程序可解析
- **一日游策略** — Day0 盘后分析 → Day1 买入 → Day2 强制平仓，差异化评级 + 流动性过滤
- **回测体系** — 单日/多日回测，命中率/踏空率/误判率一键汇总
- **SkillOpt 闭环** — `skills/*.skill.md` 解耦 Prompt，回测反馈 → 自动迭代优化

## 分析流程

```
[1] 预加载缓存 (preload)
     ├─ 公共数据: 市场情绪 + 板块排行 + 北向资金
     ├─ 历史回填: 30 天市场数据 / 板块数据
     ├─ 个股恢复: 行情 + 财务 + 舆情 + 价格历史
     └─ 辩论轨迹: 从磁盘恢复已有分析

[2] 四维分析师并行调研
     ├─ 🔬 基本面: ROE/ROA/毛利率/PE/PB (同花顺)
     ├─ 📈 技术面: OHLCV/MA5/MA10/MA20/量价 (东方财富)
     ├─ 💬 情绪面: 雪球帖子+行情 / 东财新闻 / 微博 (JinaReader)
     └─ 🏛️ 政策面: 板块动量 / 北向资金 / 市场情绪

[3] 多空辩论 (聚焦 24h 维度)
     ├─ 📈 Bull Researcher: Day1上涨逻辑（超跌反弹/涨停惯性/尾盘异动）
     ├─ 📉 Bear Researcher: 一日游风险（追高/跌停/流动性/隔夜）
     └─ Research Manager: 明日涨跌概率裁决

[4] 一日游交易决策
     ├─ 🔍 流动性检查: ST/停牌/跌停/成交额 (硬过滤)
     └─ Trader: Buy(Day1买入) or Hold(不参与)

[5] 风险讨论 (聚焦 Day2 能否顺利卖出)
     ├─ 🔥 Aggressive: 24h 持有期风险极低，超短线不需止损
     ├─ 🛡️ Conservative: Day2跌停/停牌=策略完全失效
     ├─ ⚖️ Neutral: 概率加权风险评估
     └─ Portfolio Manager: Buy(Day1买入,信心度) or Hold(不参与)

[6] 输出保存
     ├─ results/: 分析结果 (MD + JSON)
     └─ agent_cache/: 完整辩论轨迹 (MD + JSON)
```

## 覆盖股票池 (25 只)

| 板块 | 股票 |
|------|------|
| ☀️ 光伏 | 通威股份、隆基绿能、阳光电源、天合光能、迈为股份 |
| 💨 风电 | 金风科技、明阳智能、东方电缆、新强联、龙源电力 |
| 🧠 AI | 科大讯飞、寒武纪、浪潮信息、中际旭创、同花顺 |
| 🔋 储能 | 宁德时代、亿纬锂能、国轩高科、赣锋锂业、上海电气 |
| 👁️ 视觉 | 海康威视、大华股份、德赛西威、中科创达、韦尔股份 |

## License

[Apache License 2.0](./LICENSE)
