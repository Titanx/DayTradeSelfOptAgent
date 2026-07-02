# Vibe-Trading 源码对比分析

> 对 [HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) (v0.1.10) 的深度审计，与 DayTradeSelfOptAgent 架构对比。

## 一句话总结

Vibe-Trading 是一个**通用量化研究平台**（18数据源 × 7回测引擎 × 29 Swarm预设 × 456 Alpha因子），DayTradeSelfOptAgent 是一个**专精一日游自进化系统**（10-Agent管道 × SkillOpt闭环 × 25只A股 × 单策略）。两者定位互补，不可直接横向比较。

---

## 一、架构定位差异

| 维度 | Vibe-Trading | DayTradeSelfOptAgent |
|------|-------------|---------------------|
| 定位 | 通用量化研究平台（pip install可运行） | 专精一日游自进化研究系统 |
| 策略框架 | 29个Swarm预设（任意策略） | 单一策略：一日游（Day0→Buy→Day2强制平仓） |
| 市场覆盖 | A股/美股/港股/加密/期货/外汇/期权 | 仅A股25只 |
| Agent架构 | 4-Agent Swarm (DAG) | 10-Agent LangGraph (线性+条件路由) |
| 数据源 | 18个OHLCV源 + 27种数据工具 | 单源AKShare + 腾讯HTTP直连回退 |
| 回测引擎 | 7个专用引擎 + 复合引擎 | collector.py (腾讯行情K线) |
| 量化因子 | 456个Alpha (Qlib158+Alpha101+GTJA191+Academic) | 无传统因子（Agent主观判断替代） |
| 优化机制 | **无** | **SkillOpt + EvoSkill 双层闭环** ← 独有 |
| 实盘对接 | 10个Broker Connector (Robinhood/IBKR/OKX/...) | 无实盘（纯研究） |
| UI | React 19 Web UI + CLI TUI + MCP Server | 纯CLI脚本 |
| 安装方式 | `pip install vibe-trading-ai` | 源码运行 |
| 社区规模 | 50+ 贡献者，GitHub trending | 个人项目 |

---

## 二、数据层对比

### Vibe-Trading: 18源多级Fallback链

```
A股: tencent → mootdx → eastmoney → baostock → akshare → tushare → local (7级)
美股: yahoo → stooq → sina → eastmoney → yfinance → tiingo → fmp → finnhub → alphavantage → akshare → local (11级)
港股: eastmoney → yahoo → futu → yfinance → akshare → local (6级)
加密: okx → ccxt → yfinance → local (4级)
```

**核心策略**: 免封杀源优先（tencent/mootdx），需Key源靠后，local兜底。

### DayTradeSelfOptAgent: 单源 + 刚刚加入的直连回退

```
AKShare (东方财富/新浪/腾讯) → 腾讯 qt.gtimg.cn HTTP直连 (新)
```

**我们刚刚做的稳定性改进（重试/节流/腾讯直连/渐进降级）**，本质上是向Vibe-Trading的低配版靠拢。差距仍然巨大但方向正确。

### 数据工具覆盖对比

| 数据类型 | Vibe-Trading | DayTradeSelfOptAgent |
|---------|:--:|:--:|
| 龙虎榜 | ✅ 完整Tool（席位明细+上榜原因） | ❌ 计划中 |
| 限售解禁 | ✅ 完整Tool（单票+市场日历） | ❌ 计划中 |
| 融资融券 | ✅ | ❌ |
| 大宗交易 | ✅ | ❌ |
| 北向资金 | ✅ | ✅ AKShare |
| 板块资金流 | ✅ | ✅ AKShare（晚间不稳定） |
| 股东户数 | ✅ | ❌ |
| SEC EDGAR + XBRL | ✅ | ❌ |
| 研报 | ✅ | ❌ |
| 问财NL搜索 | ✅ | ❌ |

---

## 三、Agent架构对比

### Vibe-Trading Swarm (投资委员会预设)

```
Bull Advocate ──┐
                ├──(并行)──→ Risk Officer ──→ Portfolio Manager
Bear Advocate ──┘
```

- 4个Agent，YAML配置
- 每Agent有独立工具集（market_data, factor_analysis, backtest）
- 每方输出7项结构化内容（含目标价、催化剂日历、回测摘要）
- DAG依赖模型（Bull/Bear并行→CRO→PM串行）
- 通用框架，适合中长期买方研究

### DayTradeSelfOptAgent (10-Agent LangGraph)

```
Phase1: 4分析师(技术/基本面/情绪/政策) ──→ Phase2: Bull/Bear辩论 ──→ Reversal ──→ SectorRotation
    ──→ ResearchManager ──→ Phase3: 3方风控 ──→ PM ──→ Trader
```

- 10个Agent，LangGraph + StateGraph
- SkillOpt可编辑规则（`<!-- SKILLOPT-EDITABLE -->` 标记）
- 专为一日游优化（硬约束：≥1%涨幅、强制平仓、ST过滤）
- 输出绑定到Pydantic Schema
- 通过回测反馈自动优化agent prompt

### 关键差异

| | Vibe-Trading | DayTradeSelfOptAgent |
|---|-------------|---------------------|
| Agent定位 | 通用角色（多头/空头/风控/PM） | 专精角色（含分析师/反弹/板块轮动） |
| 规则来源 | 静态Skill文档（人类编写） | SkillOpt自动训练 + 人类审核 |
| 架构演进 | 手动添加Swarm预设 | EvoSkill自动发现结构性缺口 |
| prompt优化 | 无 | 每天回测后LLM分析错误→自动修改 |

---

## 四、Skill格式对比

### Vibe-Trading

```yaml
---
name: candlestick
description: Candlestick pattern recognition engine...
category: strategy
---
# Candlestick Pattern Recognition

## Purpose
## Signal Logic
## Parameters
| Parameter | Default | Description |
```

YAML Front Matter元数据，纯文档，**面向人类开发者**。无自动优化。

### DayTradeSelfOptAgent

```markdown
| version | author | updated |
|---------|--------|---------|
| v1.3.0  | SkillOpt | 2026-06-30 |

## decision_rules
<!-- SKILLOPT-EDITABLE -->
rule: 通过日内动量、次日催化剂、资金面信号...
rule: 超跌反弹：连续大跌 2-3 日后...

## decision_rules_anti
<!-- SKILLOPT-EDITABLE -->
anti: 不要用Q1季报的PE/毛利率否决一日游信号...
```

版本元数据 + SKILLOPT-EDITABLE标记，**面向AI可编辑**。每天自动训练。

---

## 五、值得借鉴的5个特性

### 1. 数据Fallback链（防封杀）⭐⭐⭐⭐⭐

```python
# Vibe-Trading 的 a_share fallback 链
FALLBACK_CHAINS["a_share"] = ["tencent", "mootdx", "eastmoney", ...]
```

**最低成本做法**: 加入 mootdx 作为第二级回退。通达信TCP协议，不封IP，零认证。

### 2. Mootdx TCP直连 ⭐⭐⭐⭐⭐

不需要API key，走通达信TCP 7709端口，是A股数据免封杀的最佳选择。Vibe-Trading把它放在tencent之后第二优先级。我们之前评估过但未实施。

### 3. 龙虎榜/限售解禁的完整封装 ⭐⭐⭐⭐

Vibe-Trading把龙虎榜做成了独立Tool类（`DragonTigerTool`），支持单票明细 + 营业部席位 + 上榜原因。限售解禁支持市场日历模式（未来N天全市场即将解禁）。这些可以直接作为我们之前计划的实现参考。

### 4. Shadow Account（交易日记→规则）⭐⭐⭐⭐

从券商导出的交易记录中提取用户的交易规律，编码为可扫描的`ShadowRule`，然后在当前市场匹配信号。概念上类似我们的SkillOpt（反馈驱动优化），但它是用户自己的交易历史驱动。

### 5. 东方财富防封节流客户端 ⭐⭐⭐

Vibe-Trading的`eastmoney` loader维护了共享的`requests.Session` + ≥1秒调用间隔 + jitter。我们刚刚在`batch_predict.py`加入了类似逻辑，可以进一步抽象为共享中间件。

---

## 六、我们独有的优势

| 特性 | 说明 |
|------|------|
| **SkillOpt 闭环自优化** | 每天回测→LLM分析错误→自动修改skill规则。Vibe-Trading完全没有这个能力 |
| **EvoSkill 架构发现** | 收敛检测→诊断能力缺口→发现缺失Agent→自动扩展架构。已从8→9→10 agent |
| **Phase 0 数据集中获取** | 解耦数据获取与agent辩论，完整性校验通过后才辩论。Vibe-Trading按需懒加载 |
| **10-Agent一日游专用管道** | 含Reversal/SectorRotation/ResearchManager/Trader等专精角色 |
| **MarketDataCache** | 公共数据的内存+磁盘双层缓存，跨交易日累积历史 |
| **策略聚焦度** | 25只A股 × 一日游 = 每日25样本 × 月500样本 = 高密度反馈 |
| **成本极低** | 每日≈7.5元（25×0.3），月≈150元 |

---

## 七、结论

**Vibe-Trading是基础设施层，DayTradeSelfOptAgent是优化层**。两者的关系不是竞品，而是互补：

- Vibe-Trading适合作为数据管道和回测引擎的底层（如果我们想支持多市场多策略）
- DayTradeSelfOptAgent展示了在单策略上如何实现Agent的闭环自进化（SkillOpt+EvoSkill）

如果我们要做**多策略/多市场**，应该借鉴Vibe-Trading的数据层和回测引擎设计。如果我们继续做**一日游深度优化**，Vibe-Trading的龙虎榜/限售解禁/mootdx等数据工具值得接入，但核心架构（SkillOpt/EvoSkill）保持独立。

---

*审计日期: 2026-07-01*  
*Vibe-Trading 版本: v0.1.10 (commit ~July 1)*
