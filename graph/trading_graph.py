"""
主编排器 — AStockAgent 核心入口

整合所有组件：LLM客户端、工具节点、图构建器、条件路由。
借鉴 TradingAgents 的 TradingAgentsGraph，适配A股场景。
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime

from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.prebuilt import ToolNode
from langgraph.graph import StateGraph

from config.default_config import get_config, set_config
from graph.setup import GraphSetup
from graph.conditional_logic import ConditionalLogic
from agents.utils.memory import TradingMemoryLog
from agents.schemas import PortfolioDecision, TraderAction, PortfolioRating

logger = logging.getLogger(__name__)


class AStockTradingGraph:
    """
    A股量化交易 Agent 主编排器

    典型用法:
        config = get_config()
        config["llm_provider"] = "deepseek"
        config["deep_think_llm"] = "deepseek-chat"

        agent = AStockTradingGraph(config=config)
        decision = agent.analyze("600519", "2024-01-15")
        print(decision)
    """

    def __init__(self, config: dict = None, debug: bool = False):
        self.config = config or get_config()
        self.debug = debug

        if debug:
            logging.basicConfig(level=logging.DEBUG)
            logger.setLevel(logging.DEBUG)

        # 初始化 LLM 客户端
        self.deep_llm = self._create_llm("deep")
        self.quick_llm = self._create_llm("quick")

        # 初始化组件
        self.tool_nodes = self._create_tool_nodes()
        self.conditional_logic = ConditionalLogic(self.config)
        self.graph_setup = GraphSetup(
            deep_llm=self.deep_llm,
            quick_llm=self.quick_llm,
            tool_nodes=self.tool_nodes,
            conditional_logic=self.conditional_logic,
            config=self.config,
        )
        self.memory = TradingMemoryLog(self.config)

        # 构建图
        self._build_graph()

    def _create_llm(self, llm_type: str):
        """
        创建 LLM 客户端

        支持: openai, deepseek, qwen, anthropic, google, ollama
        """
        provider = self.config.get("llm_provider", "deepseek")
        model = self.config.get(
            f"{llm_type}_think_llm" if llm_type == "deep"
            else "quick_think_llm",
            self.config.get("deep_think_llm", "deepseek-chat")
        )
        backend = self.config.get("backend_url")
        temperature = self.config.get("temperature", 0.3)

        api_key = None
        base_url = backend

        if provider == "openai":
            api_key = os.environ.get("OPENAI_API_KEY")
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=model, temperature=temperature,
                api_key=api_key, base_url=base_url,
            )
        elif provider == "deepseek":
            api_key = os.environ.get("DEEPSEEK_API_KEY")
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=model, temperature=temperature,
                api_key=api_key,
                base_url=base_url or "https://api.deepseek.com/v1",
            )
        elif provider == "qwen":
            api_key = os.environ.get("DASHSCOPE_API_KEY")
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=model, temperature=temperature,
                api_key=api_key,
                base_url=base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1",
            )
        elif provider == "anthropic":
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(
                model=model, temperature=temperature,
                api_key=api_key,
            )
        elif provider == "google":
            api_key = os.environ.get("GOOGLE_API_KEY")
            from langchain_google_genai import ChatGoogleGenerativeAI
            return ChatGoogleGenerativeAI(
                model=model, temperature=temperature,
                google_api_key=api_key,
            )
        elif provider == "ollama":
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=model, temperature=temperature,
                base_url=base_url or "http://localhost:11434/v1",
                api_key="ollama",
            )
        else:
            # 默认使用 OpenAI 兼容接口
            api_key = os.environ.get("OPENAI_API_KEY")
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=model, temperature=temperature,
                api_key=api_key, base_url=base_url,
            )

    def _create_tool_nodes(self) -> Dict[str, ToolNode]:
        """创建各分析师的工具节点"""
        from agents.utils.agent_utils import (
            MARKET_TOOLS, FUNDAMENTAL_TOOLS, SENTIMENT_TOOLS, POLICY_TOOLS
        )
        return {
            "tools_fundamental": ToolNode(FUNDAMENTAL_TOOLS),
            "tools_technical": ToolNode(MARKET_TOOLS),
            "tools_sentiment": ToolNode(SENTIMENT_TOOLS),
            "tools_policy": ToolNode(POLICY_TOOLS),
        }

    def _build_graph(self):
        """构建并编译 LangGraph"""
        plan = self.graph_setup.build_execution_plan()
        workflow = self.graph_setup.setup_graph(plan)
        self.graph = workflow.compile()

        if self.debug:
            logger.info("图构建完成")
            logger.info(f"分析师: {[s.name for s in plan.specs]}")
            logger.info(f"辩论轮数: {self.config.get('max_debate_rounds', 1)}")
            logger.info(f"风险辩论轮数: {self.config.get('max_risk_discuss_rounds', 1)}")

    def analyze(self, symbol: str, trade_date: str = None,
                stock_name: str = "") -> Dict[str, Any]:
        """
        运行完整的分析流水线

        Args:
            symbol: A股代码，如 "600519", "000001"
            trade_date: 分析日期 "YYYY-MM-DD"，默认今天
            stock_name: 股票名称（可选，自动获取）

        Returns:
            {
                "symbol": str,
                "trade_date": str,
                "decision": str,           # 最终决策文本
                "rating": str,             # Buy/Hold/Sell
                "action": str,             # Buy/Hold/Sell
                "confidence": float,       # 0-1
                "reports": {               # 各阶段报告
                    "fundamental": str,
                    "technical": str,
                    "sentiment": str,
                    "policy": str,
                }
            }
        """
        if trade_date is None:
            trade_date = datetime.now().strftime("%Y-%m-%d")

        # 标准化代码
        symbol = symbol.strip()
        if "." not in symbol:
            symbol = symbol.zfill(6)

        # 获取股票名称
        if not stock_name:
            stock_name = self._resolve_stock_name(symbol)

        logger.info(f"开始分析: {stock_name} ({symbol}) 日期: {trade_date}")

        # ========================================================
        # Phase 0: 自动结算历史 pending 决策的收益
        # ========================================================
        self._settle_pending_returns(symbol, trade_date)

        # 初始状态
        initial_state = {
            "messages": [],
            "symbol": symbol,
            "stock_name": stock_name,
            "trade_date": trade_date,
            "fundamental_report": "",
            "technical_report": "",
            "sentiment_report": "",
            "policy_report": "",
            "investment_debate_state": {"count": 0},
            "risk_debate_state": {"count": 0},
            "final_decision": "",
        }

        # 运行图
        try:
            final_state = self.graph.invoke(initial_state)
        except Exception as e:
            logger.error(f"图运行失败: {e}")
            raise

        # 提取决策
        decision_text = final_state.get("final_decision", "")
        rating, action, confidence = self._parse_decision(decision_text)

        # 提取各报告
        reports = {
            "fundamental": final_state.get("fundamental_report", ""),
            "technical": final_state.get("technical_report", ""),
            "sentiment": final_state.get("sentiment_report", ""),
            "policy": final_state.get("policy_report", ""),
        }

        result = {
            "symbol": symbol,
            "stock_name": stock_name,
            "trade_date": trade_date,
            "decision": decision_text,
            "rating": rating,
            "action": action,
            "confidence": confidence,
            "reports": reports,
        }

        # 持久化决策
        try:
            self.memory.store_decision(symbol, trade_date, decision_text)
        except Exception as e:
            logger.warning(f"决策持久化失败: {e}")

        # 保存结果到文件
        self._save_result(result)

        return result

    def _resolve_stock_name(self, symbol: str) -> str:
        """解析股票名称"""
        try:
            from dataflows.interface import route_to_vendor
            data = route_to_vendor("get_stock_realtime", symbol)
            if data and data.get("name"):
                return data["name"]
        except Exception:
            pass
        return ""

    def _settle_pending_returns(self, symbol: str, trade_date: str) -> None:
        """
        自动结算上次分析 pending 决策的实际收益

        流程:
        1. 查找该 ticker 的 pending 条目（上次分析时写入的决策）
        2. 用 AKShare 获取持仓期内股价 → 计算实际收益率
        3. 用基准指数计算 alpha（超额收益）
        4. LLM 生成一句反思文本
        5. 更新记忆日志（pending → resolved + 反思）

        这构成了"决策 → 等待持仓期 → 收益结算 → 反思 → 注入下次决策"的完整反馈闭环
        """
        pending = self.memory.get_pending_entries()
        ticker_pending = [(d, s, e) for d, s, e in pending if s == symbol]
        if not ticker_pending:
            return

        holding_days = self.config.get("holding_period_days", 5)
        outcomes = []

        for decision_date, decision_symbol, entry_text in ticker_pending:
            try:
                # 计算结算日期 = 决策日期 + 持仓天数
                from datetime import timedelta
                settle_date_dt = datetime.strptime(decision_date, "%Y-%m-%d") + timedelta(days=holding_days)
                settle_date = settle_date_dt.strftime("%Y%m%d")

                # 获取股价数据：决策日 vs 结算日
                from dataflows.akshare_adapter import get_stock_daily
                df = get_stock_daily(symbol, start_date=f"{decision_date.replace('-', '')[:6]}01")
                if df is None or df.empty:
                    continue

                close_prices = None
                if "close" in df.columns:
                    df["date_str"] = df["date"].dt.strftime("%Y-%m-%d") if hasattr(df["date"], "dt") else df["date"].astype(str)
                    close_prices = {r["date_str"][:10]: r["close"] for _, r in df.iterrows()}
                else:
                    continue

                decision_clean = decision_date[:10]
                settle_clean = settle_date_dt.strftime("%Y-%m-%d")

                entry_price = close_prices.get(decision_clean)
                exit_price = close_prices.get(settle_clean)
                if exit_price is None:
                    # 用最接近的交易日
                    nearby = sorted([d for d in close_prices if d <= settle_clean])
                    if nearby:
                        exit_price = close_prices[nearby[-1]]

                if entry_price is None or exit_price is None:
                    continue

                raw_return = (exit_price / entry_price - 1) * 100
                raw_return = round(raw_return, 2)

                # 提取评级信息
                import re
                rating_match = re.search(r'\*\*Rating\*\*:\s*(\w+)', entry_text)
                rating = rating_match.group(1) if rating_match else "?"

                # 简单反思（数据驱动版，不调LLM以省成本）
                if raw_return > 5:
                    hint = "大幅正收益"
                elif raw_return > 0:
                    hint = "小幅正收益"
                elif raw_return > -5:
                    hint = "小幅亏损"
                else:
                    hint = "大幅亏损"

                reflection = (
                    f"{hint}（{raw_return:+.2f}%，持仓{holding_days}天）。"
                    f"上次评级[{rating}]。"
                    f"入场{entry_price}→出场{exit_price}。"
                )

                outcomes.append((decision_date, decision_symbol, reflection))
                logger.info(f"收益结算: {symbol} {decision_date} → {raw_return:+.2f}% [{rating}]")

            except Exception as e:
                logger.warning(f"收益结算失败 [{symbol} {decision_date}]: {e}")

        if outcomes:
            self.memory.batch_update_with_outcomes(outcomes)
            logger.info(f"已结算 {len(outcomes)} 条 pending 决策")

    def _parse_decision(self, text: str) -> Tuple[str, str, float]:
        """解析决策文本中的评级和信心度，支持 Markdown 和 JSON 两种格式"""
        import re
        import json as _json

        rating = "Hold"
        action = "Hold"
        confidence = 0.5

        # 1. 尝试 Markdown 格式: **Rating**: Buy
        rating_match = re.search(r'\*\*Rating\*\*:\s*(\w+)', text)
        if rating_match:
            rating = rating_match.group(1)

        action_match = re.search(r'\*\*Action\*\*:\s*(\w+)', text)
        if action_match:
            action = action_match.group(1)

        conf_match = re.search(r'\*\*Confidence\*\*:\s*(\d+)%', text)
        if conf_match:
            try:
                confidence = float(conf_match.group(1)) / 100
            except ValueError:
                pass

        # 2. 如果 Markdown 没匹配到，尝试 JSON 格式回退
        if rating == "Hold" and action == "Hold" and confidence == 0.5:
            try:
                # 尝试提取 JSON 块
                json_match = re.search(r'\{[\s\S]*"rating"[\s\S]*\}', text)
                if json_match:
                    data = _json.loads(json_match.group(0))
                    if "decision" in data:
                        data = data["decision"]
                    rating = data.get("rating", "Hold")
                    action = data.get("action", data.get("rating", "Hold"))
                    confidence = float(data.get("confidence", 0.5))
            except Exception:
                pass

        # 3. 标准化
        rating_map = {
            "buy": "Buy", "overweight": "Overweight", "hold": "Hold",
            "underweight": "Underweight", "sell": "Sell",
        }
        rating = rating_map.get(rating.lower(), rating.title())

        action_map = {"buy": "Buy", "hold": "Hold", "sell": "Sell"}
        action = action_map.get(action.lower(), action.title())

        # 确保 confidence 在 0-1 之间
        confidence = max(0.0, min(1.0, confidence))

        return rating, action, confidence

    def _save_result(self, result: Dict):
        """保存分析结果到 ~/.astock_agent/results/，并同步到项目 results/"""
        import subprocess

        # 主存储：~/.astock_agent/results/
        try:
            home_dir = Path(self.config.get("results_dir", str(Path.home() / ".astock_agent" / "results")))
            home_dir = home_dir.expanduser()
            home_dir.mkdir(parents=True, exist_ok=True) if str(home_dir).startswith(str(Path.home())) else None

            filename = f"{result['symbol']}_{result['trade_date']}_analysis.json"
            filepath = home_dir / filename

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            logger.info(f"分析结果已保存: {filepath}")

            # 同步到项目 results/ 文件夹
            export_dir = Path(__file__).parent.parent / "results"
            export_dir.mkdir(parents=True, exist_ok=True)
            dest = export_dir / filename
            content = json.dumps(result, ensure_ascii=False, indent=2)
            try:
                dest.write_text(content, encoding="utf-8")
            except PermissionError:
                subprocess.run([
                    "powershell", "-Command",
                    f"Set-Content -Path '{dest}' -Value '{content}' -Encoding UTF8"
                ], capture_output=True)
        except Exception as e:
            logger.warning(f"结果保存失败: {e}")

    def run_batch(self, symbols: List[str], trade_date: str = None,
                  stock_names: List[str] = None) -> List[Dict]:
        """
        批量分析多只股票

        Args:
            symbols: 股票代码列表
            trade_date: 分析日期
            stock_names: 对应的股票名称列表（可选）

        Returns:
            分析结果列表
        """
        if trade_date is None:
            trade_date = datetime.now().strftime("%Y-%m-%d")

        results = []
        for i, symbol in enumerate(symbols):
            name = stock_names[i] if stock_names and i < len(stock_names) else ""
            logger.info(f"[{i+1}/{len(symbols)}] 分析 {symbol}...")
            try:
                result = self.analyze(symbol, trade_date, name)
                results.append(result)
            except Exception as e:
                logger.error(f"分析失败 [{symbol}]: {e}")
                results.append({
                    "symbol": symbol, "trade_date": trade_date,
                    "error": str(e), "rating": "Hold", "action": "Hold",
                })
        return results
