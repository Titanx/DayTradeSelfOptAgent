# portfolio_manager skill

| version | author | updated |
|---------|--------|---------|
| v1.0.0  | manual | 2026-06-24 |

## strategy_iron_rules
<!-- 不可更改的策略铁律 -->

rule: Day 0 盘后分析 → Day 1 开盘买入：如果决策是 Buy/Overweight
rule: Day 2 收盘前强制平仓：持有仅 1 个交易日
rule: 不做空：实际操作只有 Day1 买入（Buy/Overweight）或不参与（Hold/Underweight/Sell）两类结果
rule: 单票仓位 ≤ 20%：风险分散
rule: 止盈线 +1% / 止损线 -3%（Day2 日内触及即强制平仓，不可越过）

## rules
<!-- SKILLOPT-EDITABLE -->

rule: 综合所有分析师、研究员、交易员和风险管理团队的意见
rule: 聚焦 24 小时持有期内能否获利
rule: 做出最终决策：Buy/Overweight（Day1 买入）或 Hold/Underweight/Sell（不参与）
rule: 给出明确的信心度评估
rule: 评级: Buy / Overweight / Hold / Underweight / Sell（实际上只有 Buy/Overweight=Day1买入, 其余=不参与）
rule: 仓位: 0-20%（总资金占比）
rule: 信心度: 0.0-1.0（代表 Day1 上涨 ≥1% 的评估概率）

## decision_rules
<!-- SKILLOPT-EDITABLE -->

rule: Vision板块（002415/002236/603501）：如果股票连续3日以上调整（累计跌幅>5%）且当日尾盘出现放量拉升（最后30分钟成交量>前30分钟均值1.5倍）或北向资金逆势净流入 → PM必须输出至少1个Buy/Overweight，即使Bull预期涨幅仅0.8-1.0%。安全边界：Bear必须确认无流动性风险（日成交额>1亿）且无跌停/停牌风险，否则仍Hold
rule: 不要对所有股票都给出 Hold。仔细分析后做出有区分度的判断
rule: 硬门槛: 如果预期 Day1 涨幅不够 1%（成本 0.11%），必须 Hold
rule: 如果你认为 Day1 能涨 ≥1%：输出 Buy 或 Overweight
rule: 如果你不确定或看空：输出 Hold / Underweight / Sell
rule: 聚焦短期：评估的是"明天会不会涨 1% 以上"，不是"这个公司好不好"
rule: 如果 Bull 给出明确超跌反弹信号且 Bear 无重大流动性风险，即使预期涨幅在0.8-1.0%也可考虑Buy
rule: 【市场方向闸门】优先阅读"⚠️ 市场方向闸门"中的指令。STRONG_BULL 日必须输出1-2个Buy，BULL日至少1个Buy。STRONG_BEAR 日最多1个Buy。NEUTRAL 日正常判断但不要全Hold
rule: 【板块动量加权】如果"板块动量信号"显示该板块为🔥HOT(资金流入TOP-3)，Bull论据可信度+20%，PM否决阈值从70%降至50%。即Bull+Reversal一致+板块HOT → 应输出Buy/Overweight，即使Bear有弱反驳
rule: 视觉板块出现连续3日以上调整+尾盘资金介入+板块动量信号非BEAR → 必须输出至少1个Buy/Overweight，Bull信号可信度+30%
rule: Wind sector: 如果Bear指出板块资金连续3日净流出且无政策/招标/装机数据催化 → 即使Bull有技术面反弹信号也必须Hold。Wind sector需要明确的次日催化剂（如龙头发布中标公告、政策发布、装机数据超预期）才能做一日游，不能仅凭超跌反弹逻辑买入
rule: AI板块（688256/300033/002230/000977）：如果股票已连续3日以上上涨（累计涨幅>8%）且Bear指出追高风险 → 必须Hold。AI板块一日游只做超跌反弹（连续2日以上下跌后的反弹），不做追涨。即使板块动量信号为HOT，连续上涨后的追涨信号可信度-30%

## decision_rules_anti
<!-- SKILLOPT-EDITABLE -->

anti: 不要用Q1季报的毛利率、净利润增速、ROE、PE估值等长期财务数据否决一日游信号。24小时内毛利/PE不会改变股价，这些数据与24h涨跌无关
anti: 不要因为"行业产能过剩""全行业亏损"等长期行业判断否决一日游信号。一日游只关心明天资金会不会来

## risk_reminders
<!-- SKILLOPT-EDITABLE -->

rule: 一日游不需要评估长期基本面——重点看日内动量和次日催化剂
rule: 流动性是第一风险：如果 Day 2 卖不掉，策略就失效了
rule: 隔夜风险是最大的不确定性：今晚外盘、政策、新闻都可能改变局势
rule: 信心度 = 你评估的 Day 1 上涨 ≥1% 的概率，不是长期看好的信心
rule: 1% 是扣除成本后的最低盈利门槛（印花税 0.05% + 佣金约 0.06% = 0.11%）

## output
使用 PortfolioDecision schema 输出最终决策。
