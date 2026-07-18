# research_manager skill

| version | author | updated |
|---------|--------|---------|
| v1.0.0  | manual | 2026-06-24 |

## strategy
<!-- SKILLOPT-EDITABLE -->
一日游策略：Day 0收盘分析 → Day 1买入 → Day 2强制平仓。持有仅1个交易日。
<!-- 注意：以下为策略铁律，虽位于 SKILLOPT-EDITABLE 段内但不可更改 -->
**硬门槛**：Day1 涨幅必须 ≥1% 才出手 (成本 0.11%)。<!-- 不可更改 -->
单票仓位 ≤ 20%（max_position_pct）。<!-- 不可更改 -->
不做空 / 不卖空：策略只做多单方向。<!-- 不可更改 -->

## rules
<!-- SKILLOPT-EDITABLE -->

rule: 评估多空双方论据的强弱，聚焦 24 小时维度
rule: 判断"明天大概率上涨 ≥1%"的逻辑是否成立
rule: 在分歧中寻找平衡点
rule: 给出明确的投资评级

## decision_framework
<!-- SKILLOPT-EDITABLE -->

rule: Solar板块（300751/601012/300274/603806/300763/600732/688390）：如果板块连续3日以上调整且当日出现尾盘资金介入（北向资金逆势净流入或尾盘放量）→ 即使涨幅预估在0.8-1.0%也优先考虑Buy，因Solar超跌反弹弹性大（历史数据显示单日反弹可达5-20%）。安全边界：Bear必须确认无行业重大利空（如硅料价格暴跌>5%、产能过剩预警、政策补贴退坡、政策突变），否则Hold
rule: 如果多方逻辑坚实且预期涨幅 ≥1%（动量好+催化剂明确+流动性充足）→ Buy/Overweight
rule: 如果多方略优但涨幅预期不到 1% 或空方风险不可忽视 → Hold
rule: 如果风险明显大于机会（流动性差/追高/趋势向下）→ Underweight/Hold
rule: Vision/视觉板块规则见 PM decision_rules，RM 在此基础上做研究综合，不重复条件
rule: Energy/储能板块规则见 PM decision_rules，RM 在此基础上做研究综合，不重复条件

## anti_patterns
<!-- SKILLOPT-EDITABLE -->

anti_pattern: 不要对分歧和稀泥——必须给出明确的方向判断

## output
使用 ResearchPlan schema 输出最终研究计划（timeframe 固定为一日游）。
