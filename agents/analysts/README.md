# 分析师模块

负责从四个维度对目标股票进行信息收集与分析。

## 四位分析师

| 文件 | 分析师 | 职责 |
|------|--------|------|
| `fundamental_analyst.py` | 基本面分析师 | 财务数据、估值指标、行业地位分析 |
| `technical_analyst.py` | 技术面分析师 | K线形态、均线系统、技术指标、成交量分析 |
| `sentiment_analyst.py` | 舆论情绪分析师 | 雪球热帖、微博情绪、新闻舆情聚合 |
| `policy_analyst.py` | 政策分析师 | 行业政策、宏观环境、法规变化 |

## 设计思路

- 借鉴 TradingAgents 的多分析师并行收集模式
- 每位分析师输出结构化的 `FundamentalReport` / `TechnicalReport` / `SentimentReport` / `PolicyReport`
- 生成的报告作为后续研究员辩论的输入材料
