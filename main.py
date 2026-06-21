"""
AStockAgent — A股量化交易多Agent系统

主入口，提供 CLI 和 Python API 两种使用方式。

用法：
  # Python API
  from graph.trading_graph import AStockTradingGraph
  agent = AStockTradingGraph()
  result = agent.analyze("600519")

  # 命令行
  python main.py analyze --symbol 600519
  python main.py run --symbols 600519,000001,000858 --date 2024-06-15
"""

import argparse
import json
import logging
import sys
from typing import List

from config.default_config import get_config, set_config
from graph.trading_graph import AStockTradingGraph

logger = logging.getLogger(__name__)


def print_banner():
    """打印欢迎横幅"""
    print("""
    ╔══════════════════════════════════════════════╗
    ║        AStockAgent — A股量化交易Agent        ║
    ║   基于多Agent协作的数据驱动+舆论监控决策框架   ║
    ╚══════════════════════════════════════════════╝
    """)


def cmd_analyze(args):
    """分析单只股票"""
    config = get_config()
    if args.debug:
        config["debug"] = True
    if args.provider:
        config["llm_provider"] = args.provider
    if args.model:
        config["deep_think_llm"] = args.model
        config["quick_think_llm"] = args.model
    if args.debate_rounds:
        config["max_debate_rounds"] = args.debate_rounds
    if args.no_opinion:
        config["enable_opinion_monitor"] = False

    config = set_config(config)

    agent = AStockTradingGraph(config=config, debug=args.debug)
    result = agent.analyze(
        symbol=args.symbol,
        trade_date=args.date,
        stock_name=args.name or "",
    )

    _print_result(result)
    return result


def cmd_batch(args):
    """批量分析"""
    symbols = [s.strip() for s in args.symbols.split(",")]
    names = [n.strip() for n in args.names.split(",")] if args.names else []

    config = get_config()
    if args.debug:
        config["debug"] = True
    if args.provider:
        config["llm_provider"] = args.provider
    if args.model:
        config["deep_think_llm"] = args.model
        config["quick_think_llm"] = args.model

    config = set_config(config)

    agent = AStockTradingGraph(config=config, debug=args.debug)
    results = agent.run_batch(symbols, args.date, names)

    _print_batch_summary(results)
    return results


def cmd_test_tools(args):
    """测试数据工具是否正常"""
    print("🔧 测试数据工具...\n")

    # 测试 AKShare
    print("1. 测试 AKShare 行情数据...")
    try:
        from dataflows.akshare_adapter import get_stock_realtime
        result = get_stock_realtime(args.symbol or "600519")
        if result:
            print(f"   ✅ 实时行情: {result.get('name', '')} {result.get('price', '')}")
        else:
            print("   ❌ 获取行情失败")
    except ImportError:
        print("   ❌ AKShare 未安装，请运行 pip install akshare")
    except Exception as e:
        print(f"   ❌ 错误: {e}")

    # 测试雪球
    print("\n2. 测试雪球舆论监控...")
    try:
        from opinion.xueqiu_monitor import build_opinion_summary
        symbol = args.symbol or "600519"
        xq_sym = f"SH{symbol.zfill(6)}" if symbol.startswith("6") else f"SZ{symbol.zfill(6)}"
        data = build_opinion_summary(xq_sym, limit=5)
        if data and data.get("quote"):
            print(f"   ✅ 行情: {data['quote'].get('name', '')} {data['quote'].get('current', '')}")
        else:
            print("   ⚠️  雪球数据部分可用（可能需要Cookie获取帖子）")
    except ImportError:
        print("   ⚠️  Agent-Reach 雪球Channel 未安装")
    except Exception as e:
        print(f"   ⚠️  雪球连接异常: {e}")

    # 测试市场情绪
    print("\n3. 测试市场情绪数据...")
    try:
        from dataflows.akshare_adapter import get_market_sentiment
        sentiment = get_market_sentiment()
        if sentiment:
            print(f"   ✅ 上涨: {sentiment.get('up_count', '?')} | "
                  f"下跌: {sentiment.get('down_count', '?')} | "
                  f"涨停: {sentiment.get('limit_up', '?')}")
        else:
            print("   ❌ 获取失败")
    except Exception as e:
        print(f"   ❌ 错误: {e}")

    print("\n✅ 工具测试完成")


def _print_result(result: dict):
    """格式化打印单股分析结果"""
    print(f"\n{'='*60}")
    print(f"📊 {result.get('stock_name', '')} ({result['symbol']}) 分析结果")
    print(f"📅 日期: {result['trade_date']}")
    print(f"{'='*60}")

    rating = result.get("rating", "Hold")
    emoji = {"Buy": "🟢", "Overweight": "🟡", "Hold": "⚪",
             "Underweight": "🟠", "Sell": "🔴"}.get(rating, "⚪")
    print(f"\n🎯 最终评级: {emoji} {rating}")
    print(f"📈 建议动作: {result.get('action', 'Hold')}")
    print(f"💪 信心度: {result.get('confidence', 0):.0%}")

    print(f"\n📝 决策摘要:")
    decision = result.get("decision", "")
    # 提取 Executive Summary
    import re
    summary_match = re.search(r'\*\*Executive Summary\*\*:(.*?)(?:\*\*|\Z)',
                              decision, re.DOTALL)
    if summary_match:
        print(f"   {summary_match.group(1).strip()[:300]}")

    print(f"\n💾 完整报告已保存至: ~/.astock_agent/results/")


def _print_batch_summary(results: List[dict]):
    """格式化打印批量分析摘要"""
    print(f"\n{'='*60}")
    print(f"📊 批量分析摘要 ({len(results)} 只股票)")
    print(f"{'='*60}")

    for r in results:
        rating = r.get("rating", "?")
        emoji = {"Buy": "🟢", "Overweight": "🟡", "Hold": "⚪",
                 "Underweight": "🟠", "Sell": "🔴"}.get(rating, "⚪")
        name = r.get("stock_name", r.get("symbol", ""))
        error = r.get("error", "")
        if error:
            print(f"  {name}: ❌ 错误 - {error[:50]}")
        else:
            print(f"  {name}: {emoji} {rating} (置信度: {r.get('confidence', 0):.0%})")


def main():
    parser = argparse.ArgumentParser(
        description="AStockAgent — A股量化交易多Agent系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py analyze --symbol 600519                    # 分析贵州茅台
  python main.py analyze --symbol 000001 --date 2024-06-15  # 指定日期
  python main.py run --symbols 600519,000858,300750         # 批量分析
  python main.py test --symbol 600519                       # 测试数据工具
  python main.py analyze --symbol 600519 --provider deepseek # 使用DeepSeek
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="命令")

    # analyze 命令
    analyze_parser = subparsers.add_parser("analyze", help="分析单只股票")
    analyze_parser.add_argument("--symbol", "-s", required=True, help="股票代码，如 600519")
    analyze_parser.add_argument("--name", "-n", help="股票名称（可选）")
    analyze_parser.add_argument("--date", "-d", help="分析日期 YYYY-MM-DD")
    analyze_parser.add_argument("--provider", "-p", help="LLM提供商: deepseek/openai/qwen")
    analyze_parser.add_argument("--model", "-m", help="模型名称")
    analyze_parser.add_argument("--debate-rounds", type=int, help="辩论轮数")
    analyze_parser.add_argument("--no-opinion", action="store_true", help="禁用舆论监控")
    analyze_parser.add_argument("--debug", action="store_true", help="调试模式")

    # batch 命令
    batch_parser = subparsers.add_parser("run", help="批量分析多只股票")
    batch_parser.add_argument("--symbols", "-s", required=True,
                              help="股票代码，逗号分隔，如 600519,000858")
    batch_parser.add_argument("--names", "-n", help="股票名称，逗号分隔")
    batch_parser.add_argument("--date", "-d", help="分析日期 YYYY-MM-DD")
    batch_parser.add_argument("--provider", "-p", help="LLM提供商")
    batch_parser.add_argument("--model", "-m", help="模型名称")
    batch_parser.add_argument("--debug", action="store_true", help="调试模式")

    # test 命令
    test_parser = subparsers.add_parser("test", help="测试数据工具是否正常")
    test_parser.add_argument("--symbol", "-s", default="600519", help="测试用股票代码")

    args = parser.parse_args()

    print_banner()

    if args.command == "analyze":
        cmd_analyze(args)
    elif args.command == "run":
        cmd_batch(args)
    elif args.command == "test":
        cmd_test_tools(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
