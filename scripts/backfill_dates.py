"""补跑4个历史交易日: 回测需要5天样本"""
import sys, time, logging
from pathlib import Path

project_dir = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(project_dir))

from config.default_config import get_config
from graph.trading_graph import AStockTradingGraph
from dataflows.market_cache import MarketDataCache
import urllib.request, json

logging.basicConfig(level=logging.WARNING, format="%(levelname)-5s %(message)s")

STOCKS = [
    ("sz300750", "宁德时代", "储能"),
    ("sh600438", "通威股份", "光伏"),
    ("sz300033", "同花顺", "AI"),
    ("sz002202", "金风科技", "风电"),
    ("sz002415", "海康威视", "视觉"),
]

# M-scripts-6 (round-9): 业务逻辑包进 main() + __main__ 守护，
# 模块级网络调用加 try/except，避免网络失败时整个脚本崩溃且无法被 import
def main():
    # 拉取宁德时代的K线,找6月所有交易日
    sid0 = "sz300750"
    # M-scripts-6 (round-9): 网络调用加 try/except，失败时打印并返回，不再让脚本崩溃
    try:
        with urllib.request.urlopen(
            urllib.request.Request(
                f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sid0},day,,,60,qfq",
                headers={"User-Agent": "Mozilla/5.0"}
            ), timeout=10
        ) as resp:
            klines = json.loads(resp.read().decode("utf-8"))["data"][sid0]["qfqday"]
    except Exception as e:
        print(f"❌ 拉取 {sid0} K线失败: {e}")
        return

    # 找6月交易日,排除当天(0622) 和 已分析的(0618)
    existing_dates = set()
    RESULTS_DIR = project_dir / "data" / "results"
    # (round-15, C-scripts-2): glob 模式补 v10 后缀，与缓存文件命名约定对齐
    for f in RESULTS_DIR.glob("*_v10_analysis.cache.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            if d.get("trade_date"):
                existing_dates.add(d["trade_date"])
        except Exception:
            pass

    target_dates = []
    for k in klines:
        date = k[0]
        if "2026-06-" in date and date not in existing_dates and date != "2026-06-22":
            target_dates.append(date)

    target_dates = sorted(target_dates)[-4:]  # 最近4天
    print(f"已有分析: {sorted(existing_dates)}")
    print(f"待补跑: {target_dates}")
    print(f"预计: {len(target_dates)}天 x 5股 x ~3min = ~{len(target_dates)*15}min")
    print("=" * 60)

    config = get_config()
    config["max_debate_rounds"] = 1
    config["max_risk_discuss_rounds"] = 1

    CACHE = MarketDataCache.get_instance()

    for trade_date in target_dates:
        CACHE.set_trade_date(trade_date)

        # 预加载公共数据
        print(f"\n📦 预加载 {trade_date} 公共缓存...")
        try:
            CACHE.preload(symbols=["300750"])
        except Exception:
            pass

        for sid, name, sector in STOCKS:
            pure_code = sid[2:]
            # 检查是否已有
            # (round-15, C-scripts-2): cache_file 路径补 v10 后缀，否则永远找不到 cache 文件
            cache_file = RESULTS_DIR / f"{pure_code}_{trade_date}_v10_analysis.cache.json"
            if cache_file.exists():
                print(f"  {pure_code} {name}: 已有 → 跳过")
                continue

            print(f"\n{'─' * 50}")
            print(f"  🎯 {trade_date} {pure_code} {name} [{sector}]")
            print(f"{'─' * 50}")

            t0 = time.time()
            try:
                graph = AStockTradingGraph(config=config)
                result = graph.analyze(
                    symbol=pure_code,
                    trade_date=trade_date,
                    stock_name=name,
                )
                elapsed = time.time() - t0
                rating = result.get("rating", "?")
                confidence = result.get("confidence", 0)
                print(f"  📊 {rating} conf={confidence:.0%}  ⏱️ {elapsed:.0f}s")
            except Exception as e:
                elapsed = time.time() - t0
                print(f"  ❌ 失败 ({elapsed:.0f}s): {e}")

    print("\n" + "=" * 60)
    print("  补跑完成 ✅")
    print("=" * 60)


if __name__ == "__main__":
    main()
