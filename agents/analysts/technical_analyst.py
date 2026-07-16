"""
技术面分析师 Agent

分析A股的技术形态、趋势、量价关系和关键指标。
A股特色的技术分析：涨停板识别、筹码分布、龙虎榜等。

Prompt 来源: skills/technical_analyst.skill.md (SkillOpt 管理)
"""


def create_technical_analyst(llm, config: dict) -> dict:
    """创建技术面分析师"""
    from agents.utils.agent_utils import MARKET_TOOLS
    from agents.schemas import TechnicalReport
    from agents.skill_loader import get_system_prompt

    return {
        "name": "技术面分析师",
        "system_prompt": get_system_prompt("technical_analyst"),
        "tools": MARKET_TOOLS,
        "structured_output": TechnicalReport,
    }
