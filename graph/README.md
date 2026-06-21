# 图编排模块

基于 LangGraph 的多 Agent 协作图，编排整个分析流程。

## 文件说明

| 文件 | 说明 |
|------|------|
| `trading_graph.py` | 核心图定义，构建完整的 StateGraph，串联 4 个分析阶段 |
| `setup.py` | 图构建配置，绑定 LLM 节点、条件路由和结构化输出 |
| `conditional_logic.py` | 条件路由逻辑，控制 Bull→Bear 辩论跳转和风险讨论回合流转 |

## 四阶段流程

```
Phase 1: 信息收集（4 个分析师并行）
    │
Phase 2: 多空辩论（Bull ⇄ Bear，多轮）
    │
Phase 3: 交易决策（Trader 生成交易提议）
    │
Phase 4: 风控讨论（Aggressive ⇄ Conservative ⇄ Neutral）
    │
Portfolio Manager 最终输出
```

## 设计思路

- 借鉴 TradingAgents 的 LangGraph  架构
- 条件路由实现灵活的多轮辩论控制
- 支持 DeepSeek 的 JSON 回退解析（DeepSeek 不支持原生 structured output）
