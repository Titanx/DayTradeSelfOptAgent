# 工具模块

Agent 共享的工具函数和记忆系统。

## 文件说明

| 文件 | 说明 |
|------|------|
| `agent_utils.py` | 数据读取工具函数，封装了对 dataflows 层的调用，为 Agent 提供统一的数据获取接口 |
| `memory.py` | 交易记忆系统 `TradingMemoryLog`，支持存储历史决策并根据股票代码和时间上下文获取过去的分析记录 |

## 设计思路

- Agent 不直接调用 dataflows，而是通过 `agent_utils.py` 间接访问，降低耦合
- 记忆系统借鉴 TradingAgents 的 Memory 概念，用于跨会话的上下文关联
