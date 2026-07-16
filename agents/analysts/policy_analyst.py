"""
政策/宏观分析师 Agent (A股特色)

A股被称为"政策市"，政策变化对市场影响极大。
本Agent专门分析宏观政策、行业政策和监管动态对个股的影响。

Prompt 来源: skills/policy_analyst.skill.md (SkillOpt 管理)
"""


def create_policy_analyst(llm, config: dict) -> dict:
    """创建政策/宏观分析师"""
    from agents.utils.agent_utils import POLICY_TOOLS
    from agents.schemas import PolicyReport
    from agents.skill_loader import get_system_prompt

    return {
        "name": "政策/宏观分析师",
        "system_prompt": get_system_prompt("policy_analyst"),
        "tools": POLICY_TOOLS,
        "structured_output": PolicyReport,
    }
