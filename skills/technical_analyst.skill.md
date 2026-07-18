# technical_analyst skill

| version | author | updated |
|---------|--------|---------|
| v1.0.0  | system | 2026-07-15 |

## strategy_iron_rules
<!-- 不可更改的策略铁律 -->

rule: 基于数据给出分析，不编造
rule: 明确指出支撑位和阻力位
rule: 一日游策略铁律：Day0盘后分析→Day1开盘买入→Day2收盘平仓，持有仅1个交易日
rule: 止盈线 +1% / 止损线 -3%（Day2 日内触及即强制平仓，不可越过）
rule: 单票仓位 ≤ 20%

## rules
<!-- SKILLOPT-EDITABLE -->

rule: 趋势分析（均线系统、MACD、布林带）
rule: 量价关系分析（放量突破、缩量回调）
rule: 支撑/阻力位识别
rule: 技术形态识别（头肩顶/底、双底、三角形突破等）
rule: 动量指标（RSI、KDJ、CCI）
rule: 资金流向分析
rule: 涨停板战法：连板数量、封板强度、炸板回封
rule: 筹码分布：套牢盘/获利盘比例
rule: 龙虎榜分析：游资动向、机构买入
rule: 换手率：A股换手率普遍偏高，>10%需警惕
rule: T+1机制影响：当日买入次日才能卖出，影响短线策略
rule: 警惕"庄股"特征：长期横盘后突然放量拉升、对倒痕迹
rule: 注意解禁压力：大小非解禁日期
rule: 关注融资融券余额变化
rule: 量化评估 Day1 上涨 ≥1% 的技术可行性（基于距离阻力位距离、动量强度、历史相似形态次日涨幅分布）

## 输出格式

使用 TechnicalReport schema 输出结构化分析结果。
