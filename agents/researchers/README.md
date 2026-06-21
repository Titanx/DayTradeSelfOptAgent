# 研究员模块

基于分析师报告进行多空辩论，输出综合研究结论。

## 结构

| 文件 | 角色 | 职责 |
|------|------|------|
| `bull_researcher.py` | 多方研究员 + 研究管理 | Bull Researcher 从看多角度论证，Bear Researcher 从看空角度挑战，Research Manager 汇总双方观点 |

## 辩论流程

```
分析师报告
    │
    ├──→ Bull Researcher（多方论证）
    ├──→ Bear Researcher（空方挑战）
    │         │
    │    ← 反驳回合 →
    │         │
    └──→ Research Manager（汇总结论，输出 ResearchPlan）
```

## 设计思路

- 借鉴 TradingAgents 的 Bull/Bear Debate 模式
- 多轮辩论机制确保正反观点充分碰撞
- Research Manager 综合评估后输出统一研究计划
