"""
交易员 Agent — 一日游超短线策略

策略规则（硬约束）：
  Day 0 (今日收盘后): 分析决定 Day 1 是否买入
  Day 1 (次日): 开盘买入（看多则执行）
  Day 2 (第三日): 无论盈亏，收盘前强制平仓

核心逻辑：在 Day 0 收盘时判断「明天有没有大概率上涨空间」。
不追求长期价值，不设止盈止损——只有一条铁律：Day 2 必须卖。

Prompt 来源: skills/trader.skill.md (SkillOpt 管理)
"""

from agents.skill_loader import get_system_prompt


def create_trader(llm, config: dict) -> dict:
    """创建交易员"""
    from agents.schemas import TraderProposal
    return {
        "name": "一日游交易员",
        "system_prompt": get_system_prompt("trader"),
        "tools": [],
        "structured_output": TraderProposal,
    }
