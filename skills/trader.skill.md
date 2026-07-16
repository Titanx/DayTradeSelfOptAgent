# trader skill

| version | author | updated |
|---------|--------|---------|
| v1.0.0  | manual | 2026-06-24 |

## strategy_iron_rules
<!-- 不可更改的策略铁律 -->

rule: Day 0 盘后分析 → Day 1 开盘买入：如果看多，第二个交易日开盘即执行买入
rule: Day 2 收盘前强制平仓：无论盈亏，持有仅 1 个交易日，Day 2 必须卖出
rule: 不做空 / 不卖空：策略只做多单方向（Buy or Nothing）
rule: 单只股票仓位 ≤ 20%：控制单票风险

## rules
<!-- SKILLOPT-EDITABLE -->

rule: 评估"明天买入 → 后天卖出"是否有正期望
rule: Buy: 预计 Day 1 有较大概率上涨 ≥1%（覆盖印花税+佣金后仍有净利），且 Day 2 能顺利卖出
rule: Hold: 上涨概率不足、预期涨幅不到 1%、或流动性风险过高
rule: 分析维度：今日收盘动量、隔夜风险、次日催化剂、Day 2 流动性、近期趋势
rule: 硬门槛：Day1 预期涨幅必须 ≥1% 才算正期望 (成本 0.11%)

## hold_conditions
<!-- SKILLOPT-EDITABLE -->

rule: 预期 Day1 涨幅 < 1% → Hold
rule: 股票近 5 日连续大涨 → Hold (追高风险)
rule: 近期日成交额 < 5000 万元 → Hold (流动性太差)
rule: 隔夜有重大不确定性（财报发布日、政策窗口期） → Hold
rule: 趋势不明朗，涨跌概率接近 50:50 → Hold

## output
使用 TraderProposal schema 输出结构化交易提案。
