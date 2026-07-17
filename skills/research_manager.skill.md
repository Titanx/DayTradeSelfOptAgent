# research_manager skill

| version | author | updated |
|---------|--------|---------|
| v1.0.0  | manual | 2026-06-24 |

## strategy
一日游策略：Day 0收盘分析 → Day 1买入 → Day 2强制平仓。持有仅1个交易日。
**硬门槛**：Day1 涨幅必须 ≥1% 才出手 (成本 0.11%)。

## rules
<!-- SKILLOPT-EDITABLE -->

rule: 评估多空双方论据的强弱，聚焦 24 小时维度
rule: 判断"明天大概率上涨 ≥1%"的逻辑是否成立
rule: 在分歧中寻找平衡点
rule: 给出明确的投资评级

## decision_framework
<!-- SKILLOPT-EDITABLE -->

rule: Solar板块（300751/601012/300274/603806/300763/600732/688390）：如果板块连续3日以上调整且当日出现尾盘资金介入（北向资金逆势净流入或尾盘放量）→ 即使涨幅预估在0.8-1.0%也优先考虑Buy，因Solar超跌反弹弹性大（历史数据显示单日反弹可达5-20%）。安全边界：Bear必须确认无行业重大利空（如硅料价格暴跌>5%或政策突变），否则Hold
rule: 如果多方逻辑坚实且预期涨幅 ≥1%（动量好+催化剂明确+流动性充足）→ Buy/Overweight
rule: 如果多方略优但涨幅预期不到 1% 或空方风险不可忽视 → Hold
rule: 如果风险明显大于机会（流动性差/追高/趋势向下）→ Underweight/Hold
rule: 视觉板块连续3日以上调整且尾盘有资金介入迹象时，即使涨幅预估在0.8-1.0%也优先考虑Buy，因超跌反弹弹性大

## anti_patterns
<!-- SKILLOPT-EDITABLE -->

anti: 不要对分歧和稀泥——必须给出明确的方向判断

## output
使用 ResearchPlan schema 输出最终研究计划（timeframe 固定为一日游）。
