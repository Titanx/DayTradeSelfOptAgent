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


def create_reversal_analyst(llm, config: dict) -> dict:
    """创建反弹分析师 — 由 EvoSkill discovery 发现的结构性缺口。

    专门评估超跌反弹机会（RSI<30、KDJ金叉、尾盘放量企稳等），
    独立于 Bull/Bear 辩论，为 Research Manager 提供反弹视角。
    """
    from agents.schemas import ResearchPlan
    return {
        "name": "反弹分析师",
        "system_prompt": get_system_prompt("reversal_analyst"),
        "tools": [],
        "structured_output": ResearchPlan,
    }


def create_sector_rotation_analyst(llm, config: dict) -> dict:
    """创建板块轮动分析师 — 由 EvoSkill discovery (round 2) 发现。

    综合板块资金流排名、北向资金、板块涨跌排行，
    识别行业轮动信号，为 Research Manager 提供板块级 Buy/Hold 信号。
    """
    from agents.schemas import ResearchPlan
    from agents.utils.agent_utils import get_sector_fund_flow_data
    return {
        "name": "板块轮动分析师",
        "system_prompt": get_system_prompt("sector_rotation_analyst"),
        "tools": [get_sector_fund_flow_data],
        "structured_output": ResearchPlan,
    }


def create_global_macro_analyst(llm, config: dict) -> dict:
    """创建全球宏观分析师 — 由 EvoSkill (manual) 新增。

    监控美股/港股/A50期货/VIX/汇率/商品等全球市场指标，
    评估隔夜外盘环境对次日A股的影响，填补"隔夜风险"盲区。
    """
    from agents.schemas import ResearchPlan
    from agents.utils.agent_utils import get_global_macro_data
    return {
        "name": "全球宏观分析师",
        "system_prompt": get_system_prompt("global_macro_analyst"),
        "tools": [get_global_macro_data],
        "structured_output": ResearchPlan,
    }
