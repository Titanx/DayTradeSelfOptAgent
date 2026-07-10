# DayTradeSelfOptAgent

基于数据和舆论监控的 A 股一日游策略多智能体系统，集成 **SkillOpt 自我优化 + EvoSkill 结构性发现** 双层自进化闭环。

> ⚠️ **免责声明**: 本项目仅供学习研究使用，所有分析结果均不构成任何投资建议。股市有风险，投资需谨慎。

## 运行环境与成本

| 项目 | 说明 |
|------|------|
| **推理模型** | DeepSeek-V4（所有 Agent prompt 均针对 DS-V4 特性优化） |
| **单股成本** | ≈ 0.3 元（每只股票完整分析链路约 15-20 次 LLM 调用） |
| **50 股批量成本** | ≈ 15 元（含 4 分析师 + 多空辩论 + 反弹分析师 + 交易员 + 3 方风控讨论） |
| **月成本估算** | ≈ 300 元（20 个交易日 × 50 股） |

> 成本随 DeepSeek 官方定价波动，以上为 2026 年 6 月参考值。

## 策略说明：T+1 一日游 (One-Day Swing, v0.4)

```
D+0 (当日收盘后)  →  15-Agent 多空辩论 →  PM 决策 Buy/Hold
D+1 (次日开盘)    →  开盘买入 (仅 Buy/Overweight 信号)
D+2 (第三日)      →  止盈/止损/收盘平仓
```

| 规则 | 参数 |
|:--|:--|
| 止盈退出 | D+2 日内最高 ≥ 买入价+1% → 获利平仓 |
| 止损退出 | D+2 日内最低 ≤ 买入价-3% → 强制平仓 |
| 默认平仓 | 未触发止盈/止损 → D+2 收盘强制平仓 |
| 仓位约束 | 单票 ≤ 20%总仓，多信号等比压缩至 100% |
| 只做多 | 不做空、不融券，放弃下跌段 |
| 流动性过滤 | 日成交额 ≥ 1 亿，禁止 ST，回避跌停/停牌 |

> **为什么设 1% 止盈**: A股印花税+佣金 ≈ 0.11%，1% 利润覆盖 9 倍成本。7/3~7/9 三轮实盘累计 +3 止盈 vs 6 止损，止盈赚太少的根本原因是信号质量而非止盈线太窄。

## 策略设计理念

> 一日游不是追求单次收益最大化，而是 **追求反馈样本积累速度最大化**。
> 一天 50 个样本、月 1000 个样本（相当长期策略的三年），每 2 天就能验证一条 prompt 好不好。
> 基于这个反馈密度，用 SkillOpt + EvoSkill 双层架构自动优化 Agent，让命中率在闭环迭代中持续收敛。

## 核心方法论：SkillOpt + EvoSkill 双层自进化

```
┌────────── SkillOpt 层 (每日自动) ──────────┐
│                                            │
│  collector → optimizer → aggregate → select│
│                    ↓                       │
│              applier 写入 skill            │
│                    ↓                       │
│              记录 accuracy                 │
│                                            │
└────────────────────────────────────────────┘
                     ↓
          检测是否收敛 (pipeline_history)
                     ↓
          最近 3 轮 accuracy 波动 < 2%?
                     ↓
         ┌── yes ──→ EvoSkill 层触发
         │
         │   evolve.py:
         │     1. 加载全部辩论轨迹
         │     2. DeepSeek 深度分析错误样本
         │     3. 审计现有 skill 能力覆盖
         │     4. 诊断: 结构性缺口 vs 规则不足
         │     5. 输出 discovery.json
         │
         │     ↓ (人工审核)
         │
         │   needs_structural_change = True?
         │     ├─ new_agent → 创建新 skill + 注册节点
         │     ├─ new_section → 在现有 skill 加新章节
         │     └─ merge → 合并冗余 agent
         │
         └── no ──→ 继续 SkillOpt 微调
```

**SkillOpt** (Microsoft) — 将 DL 训练范式映射到文本空间：skill.md 的 rule 行 = 模型参数，回测准确率 = 损失函数，LLM 分析错误 = 梯度信号。

**EvoSkill** (Sentient) — 当 SkillOpt 收敛时，诊断能力缺口，发现缺失的 Agent 模块。本项目首轮发现 `reversal_analyst`（反弹分析师），8-agent → 9-agent。

详见 [docs/skillopt_evoskill_architecture.md](docs/skillopt_evoskill_architecture.md) 和 [daily_reports/](daily_reports/)。

---

## 架构概览 (15-Agent, v0.4)

```
用户输入（股票代码）
       │
       ▼
┌──────────────────────────────────────────┐
│          Phase 0: 大盘研判                 │
│   market_direction → sector_rotation      │
│              ↓                            │
│   🌍 global_macro_analyst (美股/港股/A50/  │
│      VIX/汇率/商品)  ← EvoSkill v0.4 新增  │
└──────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────┐
│          Phase 1: 信息收集                 │
│   基本面 │ 技术面 │ 舆论情绪 │ 政策面       │
└──────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────┐
│          Phase 2: 多空辩论                 │
│     Bull Researcher ⟷ Bear Researcher     │
│              ↓                            │
│      Reversal Analyst (反弹视角)           │
│              ↓                            │
│        Research Manager 汇总              │
└──────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────┐
│          Phase 3: 交易决策                 │
│         Trader (D+1买 D+2止盈/止损/平仓)    │
└──────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────┐
│          Phase 4: 风控讨论                 │
│  Aggressive ⟷ Conservative ⟷ Neutral      │
│              ↓                            │
│       Portfolio Manager 最终决策           │
│   Buy=D+1买入 / Hold=不参与               │
└──────────────────────────────────────────┘
```

## 快速开始

### 安装

```bash
conda create -n stocka python=3.12
conda activate stocka
pip install -r requirements.txt
```

### 配置

```bash
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY
```

### 运行

```bash
# 单只股票测试
python tests/test_one_stock.py

# 50只批量预测 (并发, 增量跳过)
python scripts/batch_predict.py                      # 默认今天
python scripts/batch_predict.py 2026-06-26           # 指定日期
python scripts/batch_predict.py 2026-06-26 --fresh   # 强制全重跑

# 回测验证
python opt/collector.py                # 收集回测信号 (HIT/MISS/STEP)
python scripts/_backtest_summary.py    # 按日期/板块查看明细

# SkillOpt 优化流水线
python opt/run_pipeline.py             # 完整 pipeline (collect → optimize → apply)
python opt/run_pipeline.py --status    # 查看 pipeline 状态 + 收敛情况

# EvoSkill 收敛检测
python opt/evolve.py --force           # 强制运行结构性发现
```

## 项目结构

```
DayTradeSelfOptAgent/
├── skills/                         # Agent Prompt (SkillOpt 可编辑)
│   ├── market_direction.skill.md
│   ├── sector_rotation.skill.md
│   ├── global_macro_analyst.skill.md  # 🆕 EvoSkill v0.4: 全球宏观分析
│   ├── bull_researcher.skill.md
│   ├── bear_researcher.skill.md
│   ├── reversal_analyst.skill.md   # 🆕 EvoSkill v0.2: 反弹分析师
│   ├── research_manager.skill.md
│   ├── trader.skill.md
│   ├── aggressive_risk.skill.md
│   ├── conservative_risk.skill.md
│   ├── neutral_risk.skill.md
│   └── portfolio_manager.skill.md
├── agents/
│   ├── analysts/              # 5 个分析师 (含market_direction/sector_rotation/global_macro)
│   ├── researchers/           # 多空研究员 + 反弹分析师
│   ├── risk_mgmt.py           # 风控讨论 + 投资经理终决
│   ├── trader.py              # T+1 交易员 (含止盈/止损)
│   ├── schemas.py             # Pydantic 数据模型
│   ├── skill_loader.py        # SkillOpt Prompt 加载器
│   └── utils/
├── dataflows/
│   ├── interface.py           # 统一数据路由
│   ├── akshare_adapter.py     # AKShare 适配器 (15+ API)
│   └── market_cache.py        # 多级缓存系统
├── graph/
│   ├── trading_graph.py       # LangGraph 主图 + 结果保存
│   ├── setup.py               # 图构建配置 (9-agent 注册)
│   └── conditional_logic.py   # 条件路由 (含 reversal_analyst)
├── opt/                       # SkillOpt + EvoSkill 优化管线
│   ├── run_pipeline.py        # 统一入口
│   ├── collector.py           # 回测信号采集
│   ├── optimizer.py           # LLM 错误分析 → edits.json
│   ├── aggregate.py           # 合并去重相似编辑
│   ├── select.py              # 四维评分 top-k 筛选
│   ├── applier.py             # 写入 SKILLOPT-EDITABLE 区域
│   ├── gate.py                # 新旧 accuracy 对比
│   ├── evolve.py              # EvoSkill 收敛检测 + 结构性发现
│   └── debate_logger.py       # 辩论轨迹归档
├── scripts/
│   ├── batch_predict.py       # 批量预测 (并发 + 增量 + 大盘预加载)
│   ├── stock_universe.py      # 统一股票配置 (50只)
│   ├── market_overview.py     # 大盘数据预加载
│   ├── generate_daily_report.py
│   ├── batch_backtest.py      # 批量回测 (HIT/STOP/FLAT/AVOID/STEP + 止损)
│   ├── _pnl.py                # 100万实盘模拟盈亏 (含仓位归一化)
│   ├── backtest_day.py
│   ├── backtest_multiday.py
│   ├── backfill_dates.py
│   └── run_batch_date.py      # 指定日期批量分析
├── docs/
│   ├── skillopt_evoskill_architecture.md  # 🆕 双层自进化架构文档
│   └── one_day_swing_strategy.md
├── daily_reports/             # 每日日报
├── main.py                    # CLI 入口
└── .env.example
```

## 覆盖股票池 (50 只, 5 板块 × 10)

| 板块 | 股票 |
|------|------|
| ☀️ 光伏 | 通威、隆基、阳光电源、天合、迈为、晶澳、福斯特、锦浪、爱旭、固德威 |
| 💨 风电 | 金风、明阳、东方电缆、新强联、龙源、天顺、运达、中材、大金、泰胜 |
| 🧠 AI | 科大讯飞、寒武纪、浪潮、中际旭创、同花顺、三六零、昆仑万维、拓尔思、海光、云从 |
| 🔋 储能 | 宁德时代、亿纬锂能、国轩、赣锋、上海电气、当升、派能、欣旺达、鹏辉、南都 |
| 👁️ 视觉 | 海康、大华、德赛西威、中科创达、韦尔、欧菲光、虹软、格灵深瞳、凌云光、奥普特 |

> 统一配置在 [scripts/stock_universe.py](scripts/stock_universe.py)，所有脚本自动引用。

## 回测记录 (T+1 + 止盈1%/止损-3%)

| 轮次 | 架构 | 样本 | HIT | STOP | AVOID | STEP | 准确率 | 100万盈亏 |
|:--|:--|:--|:--|:--|:--|:--|:--|:--|
| 6/29→7/1 | v0.3 9-agent | 50 | 3 | 0 | 9 | 38 | 24% | — |
| 6/30→7/2 | v0.3 | 50 | 0 | 1 | 20 | 29 | 42% | — |
| 7/1→7/3 | v0.3 | 25 | 0 | 0 | 12 | 13 | 48% | — |
| 7/2→7/6 | v0.3 | 50 | 0 | 0 | 19 | 31 | 38% | — |
| **7/3→7/7** | **v0.4** 🔥 | 25 | 3 | 4 | 13 | 4 | **64%** | **-1.29%** |
| 7/6→7/8 | v0.4 | 25 | 0 | 1 | 14 | 10 | 56% | -3.02% |
| 7/7→7/9 | v0.4 | 25 | 1 | 1 | 13 | 10 | 56% | -1.12% |
| **合计** | | **200** | **7** | **7** | **73** | **115** | **40%** | |

> v0.4 = 首次引入 global_macro_analyst。7/3 全周唯一有止盈的天，准确率 64% 全周最高。

## License

[Apache License 2.0](./LICENSE)

## 设计理念：用主观方法论做量化的事

本项目不是一个传统的量化交易系统（没有因子挖掘、没有回测引擎、没有实盘对接），而是一个**以主观交易方法论为基础的程序化多 Agent 系统**。

- **主观体现在**：Bull/Bear 辩论、PM 风控、ResearchManager 裁决 — 这些 Agent 的内部逻辑是交易员经验规则的 prompt 化，是一个"多个 AI 模拟交易团队开会讨论然后投票"的过程。
- **量化体现在**：一日游策略天然产生高密度反馈样本（每日 25 只 × 月 500 样本），通过回测计算 HIT/MISS/STEP/AVOID 四维指标，用 SkillOpt 闭环自动优化 Agent prompt，类似 DL 的梯度下降→参数更新过程。

核心信念：交易领域的最佳实践仍大量存在于经验规则中，与其强行做纯数据驱动的量化模型，不如先把这些经验规则系统化、程序化、可验证，让 AI 来承担"基于规则做判断"的执行层面工作。

## 参考项目

| 项目 | 说明 | 链接 |
|------|------|------|
| **AKShare** | A股/期货/外汇全品类数据接口，封装东方财富/新浪/腾讯等30+免费源 | [github.com/akfamily/akshare](https://github.com/akfamily/akshare) |
| **LangGraph** | 有状态多角色 Agent 图编排框架，支撑 10-agent 辩论→裁决→决策的复杂工作流 | [github.com/langchain-ai/langgraph](https://github.com/langchain-ai/langgraph) |
| **DeepSeek** | 高性价比 LLM，单股完整分析链路成本≈0.3元 | [github.com/deepseek-ai](https://github.com/deepseek-ai) |
| **mootdx** | TDX 行情协议 TCP 直连通道，已评估可作为 AKShare 晚间不稳定时的备选数据源 | [github.com/bopo/mootdx](https://github.com/bopo/mootdx) |
| **a-stock-data** | A股数据获取架构参考 (本地 Skill)，提供东财直连/防封节流/多源14级回退等稳定性最佳实践 | — |
