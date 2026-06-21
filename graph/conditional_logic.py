"""
条件路由逻辑

控制 LangGraph 中 Agent 节点之间的跳转。
借鉴 TradingAgents: 基于消息中 tool_calls 的工具循环路由，
以及基于发言者前缀的辩论轮转路由。
"""

import logging
from typing import Literal, Dict, Any

logger = logging.getLogger(__name__)


class ConditionalLogic:
    """条件路由器"""

    def __init__(self, config: dict):
        self.max_debate_rounds = config.get("max_debate_rounds", 1)
        self.max_risk_rounds = config.get("max_risk_discuss_rounds", 1)

    # ============================================================
    # 分析师工具循环路由
    # ============================================================

    def _should_continue_tool_loop(self, state, tool_node: str,
                                    clear_node: str) -> str:
        """
        通用工具循环路由：
        - 如果最后一条消息有 tool_calls → 进入工具节点
        - 否则 → 进入消息清理节点（本分析师完成）
        """
        messages = state.get("messages", [])
        if not messages:
            return clear_node

        last_msg = messages[-1]
        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            return tool_node

        return clear_node

    def should_continue_fundamental(self, state) -> str:
        return self._should_continue_tool_loop(
            state, "tools_fundamental", "clear_fundamental"
        )

    def should_continue_technical(self, state) -> str:
        return self._should_continue_tool_loop(
            state, "tools_technical", "clear_technical"
        )

    def should_continue_sentiment(self, state) -> str:
        return self._should_continue_tool_loop(
            state, "tools_sentiment", "clear_sentiment"
        )

    def should_continue_policy(self, state) -> str:
        return self._should_continue_tool_loop(
            state, "tools_policy", "clear_policy"
        )

    # ============================================================
    # 研究员辩论路由
    # ============================================================

    def should_continue_debate(self, state) -> str:
        """
        多空辩论路由：
        Bull ↔ Bear 轮转，达到 max 轮后 -> Research Manager
        """
        debate = state.get("investment_debate_state", {})
        count = debate.get("count", 0)
        max_rounds = self.max_debate_rounds

        if count >= 2 * max_rounds:
            return "research_manager"

        # current_response 来自最后一条AI消息
        messages = state.get("messages", [])
        if messages:
            last_ai = None
            for m in reversed(messages):
                if hasattr(m, "type") and m.type == "ai":
                    last_ai = m.content if hasattr(m, "content") else ""
                    break

            if last_ai and str(last_ai).startswith("Bull:"):
                return "bear_researcher"

        return "bull_researcher"

    # ============================================================
    # 风险辩论路由
    # ============================================================

    def should_continue_risk(self, state) -> str:
        """
        三方风险辩论路由：
        Aggressive → Conservative → Neutral → 循环 → Portfolio Manager
        """
        risk = state.get("risk_debate_state", {})
        count = risk.get("count", 0)
        max_rounds = self.max_risk_rounds

        if count >= 3 * max_rounds:
            return "portfolio_manager"

        # 判断上一个发言者
        messages = state.get("messages", [])
        last_content = ""
        if messages:
            for m in reversed(messages):
                if hasattr(m, "type") and m.type == "ai":
                    last_content = str(m.content) if hasattr(m, "content") else ""
                    break

        if "Conservative:" in last_content:
            return "neutral_risk"
        elif "Neutral:" in last_content:
            return "aggressive_risk"
        else:
            # Aggressive 发言后 → 轮到 Conservative
            return "conservative_risk"
