"""
多头研究员与空头研究员 Agent

通过结构化辩论机制，从正反两面审视分析师团队的输出。
借鉴 TradingAgents 的辩论模式（基于 current_response 前缀路由）。

Prompt 来源: skills/{bull,bear}_researcher.skill.md 和 skills/research_manager.skill.md (SkillOpt 管理)
"""

from agents.skill_loader import get_system_prompt


def create_bull_researcher(llm, config: dict) -> dict:
    """创建多头研究员"""
    from agents.schemas import ResearchPlan
    return {
        "name": "多头研究员",
        "system_prompt": get_system_prompt("bull_researcher"),
        "tools": [],
        "structured_output": ResearchPlan,
    }


def create_bear_researcher(llm, config: dict) -> dict:
    """创建空头研究员"""
    from agents.schemas import ResearchPlan
    return {
        "name": "空头研究员",
        "system_prompt": get_system_prompt("bear_researcher"),
        "tools": [],
        "structured_output": ResearchPlan,
    }


def create_research_manager(llm, config: dict) -> dict:
    """创建研究主管"""
    from agents.schemas import ResearchPlan
    return {
        "name": "研究主管",
        "system_prompt": get_system_prompt("research_manager"),
        "tools": [],
        "structured_output": ResearchPlan,
    }
