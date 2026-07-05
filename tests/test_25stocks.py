"""25股一日游测试 — 含 global_macro_analyst (EvoSkill v0.4)"""
import os, sys, time, logging, json
from pathlib import Path

project_dir = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(project_dir))

from config.default_config import get_config
from graph.trading_graph import AStockTradingGraph
from dataflows.akshare_adapter import get_latest_trade_date
from dataflows.market_cache import MarketDataCache

logging.basicConfig(level=logging.INFO, format="%(levelname)-5s %(message)s")

TRADE_DATE = get_latest_trade_date()
CACHE = MarketDataCache.get_instance()
CACHE.set_trade_date(TRADE_DATE)

TEST_STOCKS = [
    ("600438", "通威股份", "光伏"),
    ("601012", "隆基绿能", "光伏"),
    ("300274", "阳光电源", "光伏"),
    ("688599", "天合光能", "光伏"),
    ("300751", "迈为股份", "光伏"),
    ("002202", "金风科技", "风电"),
    ("601615", "明阳智能", "风电"),
    ("603606", "东方电缆", "风电"),
    ("300850", "新强联", "风电"),
    ("001289", "龙源电力", "风电"),
    ("002230", "科大讯飞", "AI"),
    ("688256", "寒武纪", "AI"),
    ("000977", "浪潮信息", "AI"),
    ("300308", "中际旭创", "AI"),
    ("300033", "同花顺", "AI"),
    ("300750", "宁德时代", "储能"),
    ("300014", "亿纬锂能", "储能"),
    ("002074", "国轩高科", "储能"),
    ("002460", "赣锋锂业", "储能"),
    ("601727", "上海电气", "储能"),
    ("002415", "海康威视", "视觉"),
    ("002236", "大华股份", "视觉"),
    ("002920", "德赛西威", "视觉"),
    ("300496", "中科创达", "视觉"),
    ("603501", "韦尔股份", "视觉"),
]

SECTOR_DESCRIPTIONS = {
    "光伏": "光伏/太阳能板块，受硅料价格、组件排产、海外需求驱动。",
    "风电": "风电设备板块，受装机量、海上风电政策、原材料成本驱动。",
    "AI": "人工智能/半导体/算力板块，受AI应用落地、芯片国产替代、算力基建驱动。",
    "储能": "储能/锂电池/新能源板块，受储能装机、锂价、新能源车政策驱动。",
    "视觉": "计算机视觉/安防/车载视觉板块，受智慧城市、自动驾驶、AI+应用落地驱动。",
}

print("=" * 70)
print(f"  25股一日游策略测试 (含全球宏观分析师)")
print(f"  交易日: {TRADE_DATE}")
print(f"  新增Agent: global_macro_analyst (美股/港股/A50/VIX/汇率/商品)")
print("=" * 70)

symbols = [s[0] for s in TEST_STOCKS]

print("\n[Phase 0] 预加载个股缓存...")
preload_status = CACHE.preload(symbols=symbols)
ok = sum(1 for v in preload_status.values() if v.startswith("OK"))
print(f"  就绪: {ok}/{len(symbols)}")

config = get_config()
config["max_debate_rounds"] = 1
config["max_risk_discuss_rounds"] = 1

print("\n" + "=" * 70)
print(f"  开始分析 25 只股票 (5板块 × 5只)...")
print("=" * 70)

results = []
buy_count = 0
hold_count = 0
sell_count = 0
errors = 0

for symbol, name, sector in TEST_STOCKS:
    print(f"\n{'─' * 60}")
    print(f"  [{sector}] {symbol} {name}")
    print(f"{'─' * 60}")

    t0 = time.time()
    try:
        cfg = dict(config)
        cfg["sector_context"] = SECTOR_DESCRIPTIONS.get(sector, "")
        graph = AStockTradingGraph(config=cfg)
        result = graph.analyze(
            symbol=symbol,
            trade_date=TRADE_DATE,
            stock_name=name,
        )
        elapsed = time.time() - t0

        rating = result.get("rating", "?")
        confidence = result.get("confidence", 0)
        action = result.get("action", "?")
        debate = result.get("debate_rounds", "?")
        risk = result.get("risk_rounds", "?")
        global_macro = result.get("reports", {}).get("global_macro", "")

        if rating.lower() in ("buy", "overweight"):
            buy_count += 1
        elif rating.lower() == "sell":
            sell_count += 1
        else:
            hold_count += 1

        bul_emoji = "🟢" if rating.lower() in ("buy", "overweight") else ("🔴" if rating.lower() == "sell" else "🟡")
        print(f"  {bul_emoji} 评级: {rating} | 仓位: {result.get('action','?')} | 信心度: {confidence:.0%}")
        print(f"  💬 辩论轮: {debate} | 风险轮: {risk} | 总消息: {result.get('messages_count','?')}")
        if len(global_macro) > 10:
            print(f"  🌍 全球宏观: 已产出 ({len(global_macro)} chars)")
        else:
            print(f"  🌍 全球宏观: (无)")

        results.append(result)

    except Exception as e:
        elapsed = time.time() - t0
        errors += 1
        print(f"  ❌ 失败 ({elapsed:.0f}s): {e}")
        import traceback
        traceback.print_exc()

print("\n" + "=" * 70)
print("  25股测试完成")
print("=" * 70)
print(f"  🟢 Buy/Overweight: {buy_count}")
print(f"  🟡 Hold: {hold_count}")
print(f"  🔴 Sell: {sell_count}")
print(f"  ❌ Error: {errors}")
print(f"  总计: {len(results)}/{len(TEST_STOCKS)} 成功")

# 汇总看多详情
if buy_count > 0:
    print(f"\n  看多明细:")
    for r in results:
        if r.get("rating", "").lower() in ("buy", "overweight"):
            print(f"    {r['symbol']} {r['stock_name']} → {r['rating']} (conf={r['confidence']:.0%})")

if errors > 0:
    print(f"\n  ⚠️ {errors} 只失败，可能是API限流或数据源不稳定")

print()
