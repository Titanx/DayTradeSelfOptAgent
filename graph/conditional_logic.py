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
        Bull ↔ Bear 轮转，达到 max 轮后 -> Reversal Analyst (反弹分析师)
        """
        debate = state.get("investment_debate_state", {})
        count = debate.get("count", 0)
        max_rounds = self.max_debate_rounds

        if count >= 2 * max_rounds:
            return "reversal_analyst"

        # current_response 来自最后一条AI消息
        messages = state.get("messages", [])
        if messages:
            last_ai = None
            for m in reversed(messages):
                if hasattr(m, "type") and m.type == "ai":
                    last_ai = m.content if hasattr(m, "content") else ""
                    break

            if last_ai:
                last_str = str(last_ai)
                if last_str.startswith("Bull:"):
                    return "bear_researcher"
                elif last_str.startswith("Bear:"):
                    return "bull_researcher"
                # M3: 兜底 — 用 count 判断下一个该谁发言，避免返回不在映射中的值导致 KeyError
                # count 为已发言数；count%2==1 表示 Bull 刚说完→下一个是 Bear；count%2==0 表示 Bear 刚说完→下一个是 Bull
                return "bull_researcher" if count % 2 == 0 else "bear_researcher"
        # 无消息时默认进入 Bull
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

        if last_content.startswith("Conservative:"):
            return "neutral_risk"
        elif last_content.startswith("Neutral:"):
            return "aggressive_risk"
        elif last_content.startswith("Aggressive:"):
            return "conservative_risk"
        else:
            # M4: 兜底用 count%3 推断下一个发言者（与 should_continue_debate 对称）
            # count 在节点内已 +1: count%3==1 → Aggressive刚说完→Conservative;
            #                    count%3==2 → Conservative刚说完→Neutral;
            #                    count%3==0 → Neutral刚说完→Aggressive
            idx = count % 3
            return ["aggressive_risk", "conservative_risk", "neutral_risk"][idx]
