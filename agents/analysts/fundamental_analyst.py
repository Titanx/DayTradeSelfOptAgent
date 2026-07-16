"""
基本面分析师 Agent

分析A股公司的财务健康状况：盈利能力、成长性、估值水平、财务风险。
使用 LangChain Agent 模式，可调用财务数据工具。

Prompt 来源: skills/fundamental_analyst.skill.md (SkillOpt 管理)
"""


def create_fundamental_analyst(llm, config: dict) -> dict:
    """
    创建基本面分析师 Agent 配置

    Returns:
        {"name": str, "system_prompt": str, "tools": list, "structured_output": type}
    """
    from agents.utils.agent_utils import FUNDAMENTAL_TOOLS
    from agents.schemas import FundamentalReport
    from agents.skill_loader import get_system_prompt

    return {
        "name": "基本面分析师",
        "system_prompt": get_system_prompt("fundamental_analyst"),
        "tools": FUNDAMENTAL_TOOLS,
        "structured_output": FundamentalReport,
    }
