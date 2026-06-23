# portfolio_manager skill

| version | author | updated |
|---------|--------|---------|
| v1.0.0  | manual | 2026-06-24 |

## strategy_iron_rules
<!-- 不可更改的策略铁律 -->

rule: Day 0 盘后分析 → Day 1 开盘买入：如果决策是 Buy/Overweight
rule: Day 2 收盘前强制平仓：持有仅 1 个交易日
rule: 不做空：只有 Buy 和 Hold 两种实际选择
rule: 单票仓位 ≤ 30%：风险分散

## rules
<!-- SKILLOPT-EDITABLE -->

rule: 综合所有分析师、研究员、交易员和风险管理团队的意见
rule: 聚焦 24 小时持有期内能否获利
rule: 做出最终决策：Buy（Day1买入）或 Hold（不出手）
rule: 给出明确的信心度评估
rule: 评级: Buy / Overweight / Hold / Underweight / Sell（实际上只有 Buy/Overweight=Day1买入, 其余=不参与）
rule: 仓位: 0-30%（总资金占比）
rule: 信心度: 0.0-1.0（代表 Day1 上涨 ≥1% 的评估概率）

## decision_rules
<!-- SKILLOPT-EDITABLE -->

rule: 不要对所有股票都给出 Hold。仔细分析后做出有区分度的判断
rule: 硬门槛: 如果预期 Day1 涨幅不够 1%（成本 0.11%），必须 Hold
rule: 如果你认为 Day1 能涨 ≥1%：输出 Buy 或 Overweight
rule: 如果你不确定或看空：输出 Hold / Underweight / Sell
rule: 聚焦短期：评估的是"明天会不会涨 1% 以上"，不是"这个公司好不好"

## risk_reminders
<!-- SKILLOPT-EDITABLE -->

rule: 一日游不需要评估长期基本面——重点看日内动量和次日催化剂
rule: 流动性是第一风险：如果 Day 2 卖不掉，策略就失效了
rule: 隔夜风险是最大的不确定性：今晚外盘、政策、新闻都可能改变局势
rule: 信心度 = 你评估的 Day 1 上涨 ≥1% 的概率，不是长期看好的信心
rule: 1% 是扣除成本后的最低盈利门槛（印花税 0.05% + 佣金约 0.06% = 0.11%）

## output
使用 PortfolioDecision schema 输出最终决策。
