"""指定日期批量运行 — 用于 A/B 对比 (如 temperature=0.1 vs 0.3)"""
import sys, time, logging, os
from pathlib import Path

project_dir = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(project_dir))
sys.path.insert(0, str(project_dir / "libs"))

from dotenv import load_dotenv
load_dotenv(project_dir / ".env", override=True)

from config.default_config import get_config
from graph.trading_graph import AStockTradingGraph
from dataflows.market_cache import MarketDataCache

from scripts.stock_universe import stocks_for_collector

STOCKS = stocks_for_collector()


def main():
    logging.basicConfig(level=logging.WARNING, format="%(levelname)-5s %(message)s")

    if len(sys.argv) < 2:
        print("用法: python run_batch_date.py 2026-06-22")
        sys.exit(1)

    TRADE_DATE = sys.argv[1]
    print(f"📅 交易日: {TRADE_DATE}")
    print(f"🔥 temperature: {get_config()['temperature']}")
    print(f"📊 股票: {len(STOCKS)} 支")
    print("=" * 60)

    config = get_config()
    config["max_debate_rounds"] = 1
    config["max_risk_discuss_rounds"] = 1

    cache = MarketDataCache.get_instance()
    cache.set_trade_date(TRADE_DATE)

    # 预加载公共缓存
    print("📦 预加载公共缓存...")
    cache.preload(symbols=["300750"])

    for sid, name, sector in STOCKS:
        code = sid[2:]
        cache_file = project_dir / "data" / "results" / f"{code}_{TRADE_DATE}_analysis.cache.json"
        if cache_file.exists():
            print(f"  {code} {name}: 已有 → 跳过")
            continue

        print(f"\n{'─'*50}")
        print(f"  🎯 {code} {name} [{sector}]")
        print(f"{'─'*50}")

        t0 = time.time()
        try:
            graph = AStockTradingGraph(config=config)
            result = graph.analyze(symbol=code, trade_date=TRADE_DATE, stock_name=name)
            elapsed = time.time() - t0
            rating = result.get("rating", "?")
            confidence = result.get("confidence", 0)
            print(f"  📊 {rating:12s} conf={confidence:.0%}  ⏱️ {elapsed:.0f}s")
        except Exception as e:
            elapsed = time.time() - t0
            print(f"  ❌ 失败 ({elapsed:.0f}s): {e}")

    print("\n" + "=" * 60)
    print("  完成 ✅")
    print("=" * 60)


if __name__ == "__main__":
    main()
