"""
舆论情绪分析师 Agent (核心新增)

基于 Agent-Reach 的雪球/微博/公众号等渠道数据，
分析市场对个股的情绪倾向和舆论热度。

这是 A股量化 Agent 与 TradingAgents 相比最重要的特色 Agent。

Prompt 来源: skills/sentiment_analyst.skill.md (SkillOpt 管理)
"""


def create_sentiment_analyst(llm, config: dict) -> dict:
    """创建舆论情绪分析师"""
    from agents.utils.agent_utils import SENTIMENT_TOOLS
    from agents.schemas import SentimentReport
    from agents.skill_loader import get_system_prompt

    return {
        "name": "舆论情绪分析师",
        "system_prompt": get_system_prompt("sentiment_analyst"),
        "tools": SENTIMENT_TOOLS,
        "structured_output": SentimentReport,
    }
