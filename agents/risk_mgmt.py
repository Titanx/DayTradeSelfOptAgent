"""
风控与投资组合管理 Agent — 一日游策略专用

三层风险分析辩论 + 最终决策：
  - 激进分析师：愿意承担一日游风险博取更高收益
  - 保守分析师：强调安全边际和流动性风险控制
  - 中性分析师：平衡风险与收益
  - 投资经理：最终拍板（Buy=Day1买入 or Hold=不出手）

策略背景（不可违背）：
  Day 0 收盘后分析 → Day 1 开盘买入 → Day 2 收盘前强制平仓

Prompt 来源: skills/{aggressive,conservative,neutral}_risk.skill.md 和 skills/portfolio_manager.skill.md (SkillOpt 管理)
"""

from agents.skill_loader import get_system_prompt


def create_aggressive_analyst(llm, config: dict) -> dict:
    return {
        "name": "激进风控分析师",
        "system_prompt": get_system_prompt("aggressive_risk"),
        "tools": [],
        "structured_output": None,
    }


def create_conservative_analyst(llm, config: dict) -> dict:
    return {
        "name": "保守风控分析师",
        "system_prompt": get_system_prompt("conservative_risk"),
        "tools": [],
        "structured_output": None,
    }


def create_neutral_analyst(llm, config: dict) -> dict:
    return {
        "name": "中立风控分析师",
        "system_prompt": get_system_prompt("neutral_risk"),
        "tools": [],
        "structured_output": None,
    }


def create_portfolio_manager(llm, config: dict) -> dict:
    """创建投资组合经理"""
    from agents.schemas import PortfolioDecision
    return {
        "name": "投资组合经理",
        "system_prompt": get_system_prompt("portfolio_manager"),
        "tools": [],
        "structured_output": PortfolioDecision,
    }
