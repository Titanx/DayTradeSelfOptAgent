"""
图构建器 — 构建 LangGraph StateGraph 工作流

完整的 Agent 流水线：

Phase 1:  基本面分析师 → 技术面分析师 → 舆论情绪分析师 → 政策分析师
Phase 2:  多头研究员 ↔ 空头研究员 (辩论) → 研究主管
Phase 3:  交易员
Phase 4:  激进风控 ↔ 保守风控 ↔ 中立风控 (三方辩论) → 投资组合经理
Phase 5:  最终决策输出
"""

import logging
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field

from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage

logger = logging.getLogger(__name__)


@dataclass
class AgentSpec:
    """Analyst Agent 规格"""
    key: str                          # 节点key，如 "fundamental"
    name: str                         # 显示名称
    create_fn: Callable               # Agent 创建函数
    tool_node_key: str                # 工具节点key
    clear_node_key: str               # 清理节点key
    state_report_key: str             # state 中的报告字段
    should_continue_fn: str           # conditional_logic 中的方法名


@dataclass
class AnalystExecutionPlan:
    """分析师执行计划"""
    specs: List[AgentSpec] = field(default_factory=list)

    def select(self, keys: List[str]) -> "AnalystExecutionPlan":
        """按 key 筛选"""
        selected = [s for s in self.specs if s.key in keys]
        return AnalystExecutionPlan(specs=selected)


class GraphSetup:
    """LangGraph 图构建器"""

    def __init__(self, deep_llm, quick_llm, tool_nodes: Dict[str, ToolNode],
                 conditional_logic, config: dict):
        self.deep_llm = deep_llm
        self.quick_llm = quick_llm
        self.tool_nodes = tool_nodes
        self.conditional_logic = conditional_logic
        self.config = config

    def build_execution_plan(self) -> AnalystExecutionPlan:
        """构建分析师执行计划"""
        from agents.analysts.fundamental_analyst import create_fundamental_analyst
        from agents.analysts.technical_analyst import create_technical_analyst
        from agents.analysts.sentiment_analyst import create_sentiment_analyst
        from agents.analysts.policy_analyst import create_policy_analyst

        specs = [
            AgentSpec(
                key="fundamental", name="基本面分析师",
                create_fn=create_fundamental_analyst,
                tool_node_key="tools_fundamental", clear_node_key="clear_fundamental",
                state_report_key="fundamental_report",
                should_continue_fn="should_continue_fundamental",
            ),
            AgentSpec(
                key="technical", name="技术面分析师",
                create_fn=create_technical_analyst,
                tool_node_key="tools_technical", clear_node_key="clear_technical",
                state_report_key="technical_report",
                should_continue_fn="should_continue_technical",
            ),
            AgentSpec(
                key="sentiment", name="舆论情绪分析师",
                create_fn=create_sentiment_analyst,
                tool_node_key="tools_sentiment", clear_node_key="clear_sentiment",
                state_report_key="sentiment_report",
                should_continue_fn="should_continue_sentiment",
            ),
            AgentSpec(
                key="policy", name="政策分析师",
                create_fn=create_policy_analyst,
                tool_node_key="tools_policy", clear_node_key="clear_policy",
                state_report_key="policy_report",
                should_continue_fn="should_continue_policy",
            ),
        ]

        return AnalystExecutionPlan(specs=specs)

    def setup_graph(self, plan: AnalystExecutionPlan) -> StateGraph:
        """构建完整的 StateGraph"""

        from langgraph.graph import StateGraph, END, START
        from typing import Annotated, TypedDict
        from langgraph.graph.message import add_messages
        from langchain_core.messages import RemoveMessage

        # 定义 AgentState
        class AgentState(TypedDict):
            messages: Annotated[List[BaseMessage], add_messages]
            symbol: str
            stock_name: str
            trade_date: str
            fundamental_report: Optional[str]
            technical_report: Optional[str]
            sentiment_report: Optional[str]
            policy_report: Optional[str]
            investment_debate_state: Optional[Dict]
            risk_debate_state: Optional[Dict]
            final_decision: Optional[str]
            market_overview: Optional[str]     # EvoSkill v0.2: 大盘/板块共享数据
            market_direction: Optional[str]    # 市场方向闸门: STRONG_BULL/BULL/NEUTRAL/BEAR/STRONG_BEAR + 闸门指令
            sector_momentum: Optional[str]     # 板块动量: HOT/WARM/NEUTRAL 资金流入信号
            sector_context: Optional[str]      # EvoSkill v0.2: 板块特定上下文
            data_context: Optional[str]        # Phase 0: 预计算的完整数据 (解耦数据获取)
            global_macro_report: Optional[str] # EvoSkill v0.4: 全球宏观分析 (美股/港股/VIX/汇率/商品)

        workflow = StateGraph(AgentState)

        cl = self.conditional_logic
        deep = self.deep_llm
        quick = self.quick_llm

        # ========================================================
        # Phase 1: 分析师节点 (循环构建)
        # ========================================================

        for spec in plan.specs:
            agent_cfg = spec.create_fn(quick, self.config)

            # 创建分析师节点函数
            def make_analyst_node(cfg, report_key):
                def node_fn(state: AgentState) -> dict:
                    context = (
                        f"## 分析任务\n"
                        f"- 股票代码: {state['symbol']}\n"
                        f"- 股票名称: {state.get('stock_name', '')}\n"
                        f"- 分析日期: {state['trade_date']}\n\n"
                    )

                    data_context = state.get("data_context", "")
                    if data_context:
                        context += f"## 预计算数据 (请仅使用以下数据进行分析)\n{data_context}\n\n"
                        context += "请基于以上数据输出你的分析报告。不要请求额外数据。\n"
                    else:
                        context += "请调用工具获取数据，然后给出分析报告。\n"

                    # 注入历史记忆
                    try:
                        from agents.utils.memory import TradingMemoryLog
                        memory = TradingMemoryLog(self.config)
                        past = memory.get_past_context(state["symbol"])
                        if past:
                            context += f"\n## 历史决策参考\n{past}\n"
                    except Exception as e:
                        logger.debug(f"历史决策加载失败: {e}")

                    # 有预计算数据时无需绑定工具
                    if data_context:
                        all_messages = [
                            SystemMessage(content=cfg["system_prompt"]),
                            HumanMessage(content=context),
                        ]
                        response = quick.invoke(all_messages)
                    else:
                        tools = cfg.get("tools", [])
                        if tools:
                            from langchain_openai import ChatOpenAI
                            llm_bound = quick
                            if hasattr(llm_bound, 'bind_tools'):
                                llm_bound = llm_bound.bind_tools(tools)
                            response = llm_bound.invoke([
                                SystemMessage(content=cfg["system_prompt"]),
                                HumanMessage(content=context),
                            ] + list(state["messages"]))
                        else:
                            response = quick.invoke([
                                SystemMessage(content=cfg["system_prompt"]),
                                HumanMessage(content=context),
                            ])
                    return {"messages": [response]}
                return node_fn

            # 创建清理节点函数
            def make_clear_node(report_key):
                def node_fn(state: AgentState) -> dict:
                    messages = state["messages"]
                    # 提取最后一条AI消息的内容作为报告
                    report_content = ""
                    for m in reversed(messages):
                        if hasattr(m, "type") and m.type == "ai":
                            report_content = str(m.content) if hasattr(m, "content") else ""
                            break

                    # 清理之前的所有消息
                    remove_msgs = [RemoveMessage(id=m.id) for m in messages if hasattr(m, "id")]

                    return {
                        report_key: report_content,
                        "messages": remove_msgs,
                    }
                return node_fn

            # 添加节点
            workflow.add_node(
                spec.key,
                make_analyst_node(agent_cfg, spec.state_report_key)
            )
            workflow.add_node(
                spec.tool_node_key,
                self.tool_nodes.get(spec.tool_node_key, ToolNode([]))
            )
            workflow.add_node(
                spec.clear_node_key,
                make_clear_node(spec.state_report_key)
            )

        # ========================================================
        # Phase 2: 研究员辩论节点
        # ========================================================
        from agents.researchers.bull_researcher import (
            create_bull_researcher, create_bear_researcher, create_research_manager,
            create_reversal_analyst, create_sector_rotation_analyst,
            create_global_macro_analyst,
        )

        def make_researcher_node(cfg, role_prefix: str):
            def node_fn(state: AgentState) -> dict:
                context = self._build_debate_context(state)
                messages = [SystemMessage(content=cfg["system_prompt"]),
                           HumanMessage(content=context)]
                response = quick.invoke(messages)
                # 确保前缀
                content = str(response.content)
                if not content.startswith(role_prefix):
                    content = f"{role_prefix}{content}"
                response.content = content
                # 更新辩论状态
                debate = state.get("investment_debate_state", {"count": 0})
                debate["count"] = debate.get("count", 0) + 1
                return {"messages": [response], "investment_debate_state": debate}
            return node_fn

        workflow.add_node("bull_researcher",
                         make_researcher_node(create_bull_researcher(quick, self.config), "Bull: "))
        workflow.add_node("bear_researcher",
                         make_researcher_node(create_bear_researcher(quick, self.config), "Bear: "))

        # 反弹分析师 — EvoSkill 发现的结构性缺口，独立评估超跌反弹机会
        def reversal_analyst_node(state: AgentState) -> dict:
            cfg = create_reversal_analyst(deep, self.config)
            context = self._build_debate_context(state)
            # 注入 Bull/Bear 辩论摘要
            debate_summary = []
            for m in state.get("messages", []):
                c = str(m.content)
                if "Bull:" in c or "Bear:" in c:
                    debate_summary.append(c[-600:])
            if debate_summary:
                context += "\n## 多空辩论摘要\n" + "\n".join(debate_summary[-4:])
            context += "\n\n请评估当前是否存在超跌反弹机会，输出以 'Reversal: ' 开头的结构化分析。"
            messages = [SystemMessage(content=cfg["system_prompt"]),
                       HumanMessage(content=context)]
            response = deep.invoke(messages)
            content = str(response.content)
            if not content.startswith("Reversal:"):
                content = "Reversal: " + content
            response.content = content
            return {"messages": [response]}
        workflow.add_node("reversal_analyst", reversal_analyst_node)

        # 板块轮动分析师 — EvoSkill round 2 发现，综合资金流+板块排行评估行业信号
        def sector_rotation_analyst_node(state: AgentState) -> dict:
            cfg = create_sector_rotation_analyst(deep, self.config)
            context = self._build_debate_context(state)
            sector_ctx = state.get("sector_context", "")
            if sector_ctx:
                context = "## 当前板块\n{}\n\n".format(sector_ctx) + context

            data_context = state.get("data_context", "")
            if data_context:
                context += "\n\n## 板块资金流与市场数据\n{}".format(data_context)
                context += "\n\n请基于以上资金流数据分析5个持仓板块的强弱，输出以 'Sector: ' 开头的结构化分析。"
            else:
                context += "\n\n请使用 get_sector_fund_flow_data() 获取板块资金流，评估5个持仓板块的强弱，输出以 'Sector: ' 开头的结构化分析。"

            messages = [SystemMessage(content=cfg["system_prompt"]),
                       HumanMessage(content=context)]
            response = deep.invoke(messages)
            content = str(response.content)
            if not content.startswith("Sector:"):
                content = "Sector: " + content
            response.content = content
            return {"messages": [response]}
        workflow.add_node("sector_rotation_analyst", sector_rotation_analyst_node)

        # 全球宏观分析师 — EvoSkill v0.4，监控美股/港股/A50/VIX/汇率/商品
        def global_macro_analyst_node(state: AgentState) -> dict:
            cfg = create_global_macro_analyst(deep, self.config)
            context = self._build_debate_context(state)
            data_context = state.get("data_context", "")
            if data_context:
                context += "\n\n## 全球市场数据\n{}".format(data_context)

            # 注入前序研究员结论摘要
            summary_parts = []
            for m in state.get("messages", []):
                c = str(m.content)
                if any(p in c for p in ["Bull:", "Bear:", "Reversal:", "Sector:"]):
                    summary_parts.append(c[-500:])
            if summary_parts:
                context += "\n\n## 前序分析摘要\n" + "\n".join(summary_parts[-5:])

            context += "\n\n请调用 get_global_macro_data() 获取全球市场数据，输出以 'Global: ' 开头的隔夜环境评估。"
            messages = [SystemMessage(content=cfg["system_prompt"]),
                       HumanMessage(content=context)]
            response = deep.invoke(messages)
            content = str(response.content)
            if not content.startswith("Global:"):
                content = "Global: " + content
            response.content = content

            # 提取报告存入 state
            return {"messages": [response], "global_macro_report": content}
        workflow.add_node("global_macro_analyst", global_macro_analyst_node)

        # 研究主管
        def research_manager_node(state: AgentState) -> dict:
            cfg = create_research_manager(deep, self.config)
            context = self._build_manager_context(state)
            messages = [SystemMessage(content=cfg["system_prompt"]),
                       HumanMessage(content=context)]
            response = deep.invoke(messages)
            return {"messages": [response]}
        workflow.add_node("research_manager", research_manager_node)

        # ========================================================
        # Phase 3: 交易员
        # ========================================================
        from agents.trader import create_trader

        def trader_node(state: AgentState) -> dict:
            cfg = create_trader(quick, self.config)
            context = self._build_trader_context(state)
            messages = [SystemMessage(content=cfg["system_prompt"]),
                       HumanMessage(content=context)]
            response = quick.invoke(messages)
            return {"messages": [response]}
        workflow.add_node("trader", trader_node)

        # ========================================================
        # Phase 4: 风险辩论 + 投资经理
        # ========================================================
        from agents.risk_mgmt import (
            create_aggressive_analyst, create_conservative_analyst,
            create_neutral_analyst, create_portfolio_manager,
        )

        def make_risk_node(cfg, prefix: str):
            def node_fn(state: AgentState) -> dict:
                context = self._build_risk_context(state)
                messages = [SystemMessage(content=cfg["system_prompt"]),
                           HumanMessage(content=context)]
                response = quick.invoke(messages)
                content = str(response.content)
                if not content.startswith(prefix):
                    content = f"{prefix}{content}"
                response.content = content
                risk = state.get("risk_debate_state", {"count": 0})
                risk["count"] = risk.get("count", 0) + 1
                return {"messages": [response], "risk_debate_state": risk}
            return node_fn

        workflow.add_node("aggressive_risk",
                         make_risk_node(create_aggressive_analyst(quick, self.config), "Aggressive: "))
        workflow.add_node("conservative_risk",
                         make_risk_node(create_conservative_analyst(quick, self.config), "Conservative: "))
        workflow.add_node("neutral_risk",
                         make_risk_node(create_neutral_analyst(quick, self.config), "Neutral: "))

        # 投资组合经理
        def portfolio_manager_node(state: AgentState) -> dict:
            cfg = create_portfolio_manager(deep, self.config)
            context = self._build_pm_context(state)
            messages = [SystemMessage(content=cfg["system_prompt"]),
                       HumanMessage(content=context)]

            # 绑定结构化输出 schema
            schema_cls = cfg.get("structured_output")
            if schema_cls:
                try:
                    llm_structured = deep.with_structured_output(schema_cls)
                    decision = llm_structured.invoke(messages)
                    # 渲染为 Markdown 格式，供 _parse_decision 解析
                    from agents.schemas import render_portfolio_decision
                    decision_text = render_portfolio_decision(decision)
                    return {
                        "messages": [AIMessage(content=decision_text)],
                        "final_decision": decision_text,
                    }
                except Exception as e:
                    logger.warning(f"结构化输出失败，回退到自由文本: {e}")

            # 回退：无 schema 时使用自由文本
            response = deep.invoke(messages)
            return {
                "messages": [response],
                "final_decision": str(response.content),
            }
        workflow.add_node("portfolio_manager", portfolio_manager_node)

        # ========================================================
        # 连接边
        # ========================================================

        # Phase 1: 分析师链式连接
        prev_clear = None
        for i, spec in enumerate(plan.specs):
            # 工具循环
            workflow.add_conditional_edges(
                spec.key,
                getattr(cl, spec.should_continue_fn),
                {spec.tool_node_key: spec.tool_node_key, spec.clear_node_key: spec.clear_node_key}
            )
            workflow.add_edge(spec.tool_node_key, spec.key)
            # 分析师完成 → 清理 → 下一个
            if i == 0:
                workflow.add_edge(START, spec.key)
                prev_clear = spec.clear_node_key
            else:
                workflow.add_edge(prev_clear, spec.key)
                prev_clear = spec.clear_node_key

        # Phase 2: 最后一个分析师 → 多空辩论 → 反弹分析师 → 板块轮动
        last_clear = plan.specs[-1].clear_node_key
        workflow.add_edge(last_clear, "bull_researcher")
        workflow.add_conditional_edges(
            "bull_researcher", cl.should_continue_debate,
            {"bear_researcher": "bear_researcher", "reversal_analyst": "reversal_analyst"}
        )
        workflow.add_conditional_edges(
            "bear_researcher", cl.should_continue_debate,
            {"bull_researcher": "bull_researcher", "reversal_analyst": "reversal_analyst"}
        )
        # 反弹分析师 → 板块轮动分析师 → 全球宏观分析师 → 研究主管
        workflow.add_edge("reversal_analyst", "sector_rotation_analyst")
        workflow.add_edge("sector_rotation_analyst", "global_macro_analyst")
        workflow.add_edge("global_macro_analyst", "research_manager")

        # Phase 3: 研究主管 → 交易员
        workflow.add_edge("research_manager", "trader")

        # Phase 4: 交易员 → 风险辩论 → 投资经理
        workflow.add_edge("trader", "aggressive_risk")
        workflow.add_conditional_edges(
            "aggressive_risk", cl.should_continue_risk,
            {"conservative_risk": "conservative_risk", "neutral_risk": "neutral_risk",
             "portfolio_manager": "portfolio_manager"}
        )
        workflow.add_conditional_edges(
            "conservative_risk", cl.should_continue_risk,
            {"neutral_risk": "neutral_risk", "aggressive_risk": "aggressive_risk",
             "portfolio_manager": "portfolio_manager"}
        )
        workflow.add_conditional_edges(
            "neutral_risk", cl.should_continue_risk,
            {"aggressive_risk": "aggressive_risk", "conservative_risk": "conservative_risk",
             "portfolio_manager": "portfolio_manager"}
        )

        # Phase 5: 投资经理 → 结束
        workflow.add_edge("portfolio_manager", END)

        return workflow

    # ============================================================
    # 上下文构建辅助方法
    # ============================================================

    def _build_debate_context(self, state: dict) -> str:
        """为研究员辩论构建上下文"""
        parts = [f"## 分析标的: {state.get('stock_name', '')} ({state['symbol']})",
                 f"分析日期: {state['trade_date']}\n"]

        overview = state.get("market_overview", "")
        if overview:
            parts.append(f"### 大盘背景\n{overview[:800]}\n")

        # 注入宏观市场数据，让Bull/Bear在辩论中知道隔夜外盘环境
        data_context = state.get("data_context", "")
        if data_context:
            parts.append(f"### 🌍 全球市场数据 (隔夜环境)\n{data_context[:600]}\n")

        direction = state.get("market_direction", "")
        if direction:
            parts.append(f"### ⚠️ 市场方向闸门\n{direction}\n")

        reports = {
            "基本面分析": state.get("fundamental_report", ""),
            "技术面分析": state.get("technical_report", ""),
            "舆论情绪分析": state.get("sentiment_report", ""),
            "政策面分析": state.get("policy_report", ""),
        }

        for title, content in reports.items():
            if content:
                parts.append(f"### {title}\n{content}\n")

        parts.append("\n请基于以上分析报告，给出你的研究和辩论观点。")
        return "\n".join(parts)

    def _build_manager_context(self, state: dict) -> str:
        """为研究主管构建上下文"""
        parts = [
            f"## 投资决策任务\n",
            f"### 股票: {state.get('stock_name', '')} ({state['symbol']})",
            f"### 日期: {state['trade_date']}\n",
            "### 分析师报告",
        ]
        for rpt in ["fundamental_report", "technical_report",
                     "sentiment_report", "policy_report"]:
            content = state.get(rpt, "")
            if content:
                parts.append(f"\n{content}\n")

        parts.append("\n### 多空辩论记录\n")
        # 取辩论阶段的消息
        for m in state.get("messages", []):
            c = str(m.content) if hasattr(m, "content") else ""
            if "Bull:" in c or "Bear:" in c:
                parts.append(c + "\n")

        # 反弹分析师独立视角
        parts.append("\n### 反弹分析师评估\n")
        reversal_found = False
        for m in state.get("messages", []):
            c = str(m.content) if hasattr(m, "content") else ""
            if c.startswith("Reversal:"):
                parts.append(c + "\n")
                reversal_found = True
        if not reversal_found:
            parts.append("(反弹分析师未产生评估)\n")

        # 板块轮动分析师 (EvoSkill v0.3)
        parts.append("\n### 板块轮动分析\n")
        sector_found = False
        for m in state.get("messages", []):
            c = str(m.content) if hasattr(m, "content") else ""
            if c.startswith("Sector:"):
                parts.append(c + "\n")
                sector_found = True
        if not sector_found:
            parts.append("(板块轮动分析师未产生评估)\n")

        # 全球宏观分析 (EvoSkill v0.4)
        global_macro = state.get("global_macro_report", "")
        if global_macro:
            parts.append("\n### 全球宏观环境\n")
            parts.append(global_macro + "\n")
            parts.append("【指令】请将全球宏观环境评估纳入你的研究计划，特别是VIX恐慌指数和A50期货信号对隔夜风险的影响。\n")

        parts.append("\n请综合以上所有信息，给出最终研究投资计划。")
        parts.append("\n特别关注: 1)反弹分析师是否发现了 Bull/Bear 忽略的超跌反弹机会;")
        parts.append(" 2)板块轮动分析师是否提供了板块级别的 Buy/Hold 信号。")
        return "\n".join(parts)

    def _build_trader_context(self, state: dict) -> str:
        """为交易员构建上下文"""
        parts = [
            f"## 交易任务\n",
            f"交易标的: {state.get('stock_name', '')} ({state['symbol']})",
            f"交易日期: {state['trade_date']}\n",
            "请基于以下研究报告制定交易方案。\n",
        ]
        for m in state.get("messages", []):
            c = str(m.content) if hasattr(m, "content") else ""
            if "Research Plan" in c or "研究计划" in c or "Investment Thesis" in c:
                parts.append(c)
                break

        # 注入全球宏观摘要
        macro = state.get("global_macro_report", "")
        if macro:
            parts.append(f"\n### 全球宏观参考\n{macro[:300]}\n")

        return "\n".join(parts)

    def _build_risk_context(self, state: dict) -> str:
        """为风险分析师构建上下文"""
        parts = [
            f"## 风险评估任务\n",
            f"标的: {state.get('stock_name', '')} ({state['symbol']})",
            f"日期: {state['trade_date']}\n",
            "请基于交易提案和前期分析，进行风险评估。\n",
        ]

        for rpt in ["fundamental_report", "sentiment_report", "policy_report", "technical_report"]:
            content = state.get(rpt, "")
            if content:
                parts.append(f"\n{content[:500]}\n")

        # 注入全球宏观报告，让风险分析师知道VIX/A50/汇率
        macro = state.get("global_macro_report", "")
        if macro:
            parts.append(f"\n### 全球宏观环境\n{macro[:400]}\n")

        # 交易员提案
        for m in state.get("messages", []):
            c = str(m.content) if hasattr(m, "content") else ""
            if "Action:" in c or "Position:" in c:
                parts.append(f"\n### 交易提案\n{c}")
                break

        return "\n".join(parts)

    def _build_pm_context(self, state: dict) -> str:
        """为投资经理构建最终决策上下文"""
        parts = [
            f"## 最终投资决策\n\n",
            f"### 基本信息\n- 股票: {state.get('stock_name', '')} ({state['symbol']})",
            f"- 日期: {state['trade_date']}\n",
        ]

        overview = state.get("market_overview", "")
        if overview:
            parts.append(f"### 大盘背景\n{overview[:600]}\n")

        direction = state.get("market_direction", "")
        if direction:
            parts.append(f"### ⚠️ 市场方向闸门 (必须遵守)\n{direction}\n")
        else:
            parts.append(f"### ⚠️ 市场方向闸门 (默认)\nNEUTRAL — 未检测到明确市场方向信号，按默认规则正常判断，不要全Hold\n")

        sector_momentum = state.get("sector_momentum", "")
        if sector_momentum:
            parts.append(f"### 板块动量信号\n本股票所属板块: {state.get('stock_name','')} → {sector_momentum}\n")
            if "HOT" in sector_momentum:
                parts.append("【板块动量指令】该板块为当日资金流入TOP-3，Bull论据可信度自动+20%。如果Bull给出买入信号且Bear反驳薄弱，应优先考虑Buy或Overweight。\n")

        sector_ctx = state.get("sector_context", "")
        if sector_ctx:
            parts.append(f"### 板块背景\n{sector_ctx[:400]}\n")

        # 全球宏观环境 (EvoSkill v0.4)
        global_macro = state.get("global_macro_report", "")
        if global_macro:
            parts.append(f"### 🌍 全球宏观隔夜环境\n{global_macro[:1200]}\n")
            if "Bearish" in global_macro:
                parts.append("【全球宏观指令】隔夜外盘偏空，请优先评估隔夜风险。VIX高企或外盘大跌时，最多1个Buy且仓位≤10%。\n")
            elif "Bullish" in global_macro:
                parts.append("【全球宏观指令】隔夜外盘偏暖，全球风险偏好有利。可以更积极地寻找Buy机会。\n")

        # 所有分析报告
        for rpt_name, rpt_key in [
            ("基本面分析", "fundamental_report"),
            ("技术面分析", "technical_report"),
            ("舆论情绪分析", "sentiment_report"),
            ("政策面分析", "policy_report"),
        ]:
            content = state.get(rpt_key, "")
            if content:
                parts.append(f"### {rpt_name}\n{content}\n")

        # 风险辩论
        parts.append("### 风险辩论\n")
        for m in state.get("messages", []):
            c = str(m.content) if hasattr(m, "content") else ""
            if any(p in c for p in ["Aggressive:", "Conservative:", "Neutral:"]):
                parts.append(c + "\n")

        parts.append("\n请综合所有信息，做出最终投资决策。使用 PortfolioDecision schema。")
        return "\n".join(parts)
