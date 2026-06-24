"""批量预测脚本 — 全25股分析，输出到 data/results/"""
import sys, time, os
from pathlib import Path
from dotenv import load_dotenv

project_dir = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(project_dir))
sys.path.insert(0, str(project_dir / "libs"))
load_dotenv(project_dir / ".env", override=True)

from config.default_config import get_config
from graph.trading_graph import AStockTradingGraph

TRADE_DATE = "2026-06-24"
STOCKS = [
    ("600438","通威股份","光伏"),("601012","隆基绿能","光伏"),("300274","阳光电源","光伏"),
    ("688599","天合光能","光伏"),("300751","迈为股份","光伏"),
    ("002202","金风科技","风电"),("601615","明阳智能","风电"),("603606","东方电缆","风电"),
    ("300850","新强联","风电"),("001289","龙源电力","风电"),
    ("002230","科大讯飞","AI"),("688256","寒武纪","AI"),("000977","浪潮信息","AI"),
    ("300308","中际旭创","AI"),("300033","同花顺","AI"),
    ("300750","宁德时代","储能"),("300014","亿纬锂能","储能"),("002074","国轩高科","储能"),
    ("002460","赣锋锂业","储能"),("601727","上海电气","储能"),
    ("002415","海康威视","视觉"),("002236","大华股份","视觉"),("002920","德赛西威","视觉"),
    ("300496","中科创达","视觉"),("603501","韦尔股份","视觉"),
]

config = get_config()
config["max_debate_rounds"] = 1
config["max_risk_discuss_rounds"] = 1

print(f"📅 交易日: {TRADE_DATE} | 股票: {len(STOCKS)} 支 | temperature: {config['temperature']}")
print("=" * 60)

agent = AStockTradingGraph(config=config)

start_time = time.time()
results = []

for i, (code, name, sector) in enumerate(STOCKS, 1):
    elapsed = time.time() - start_time
    eta = (elapsed / max(i - 1, 1)) * (len(STOCKS) - i + 1) if i > 1 else 0

    cache_file = project_dir / "data" / "results" / f"{code}_{TRADE_DATE}_analysis.cache.json"
    if cache_file.exists():
        print(f"[{i:2d}/{len(STOCKS)}] {code} {name}: 已有 → 跳过")
        continue

    print(f"[{i:2d}/{len(STOCKS)}] {code} {name} ({sector}) | ETA {eta/60:.1f}min", end=" ", flush=True)

    t0 = time.time()
    try:
        result = agent.analyze(symbol=code, trade_date=TRADE_DATE, stock_name=name)
        dt = time.time() - t0
        rating = result.get("rating", "?")
        conf = result.get("confidence", 0)
        print(f"→ {rating} (conf={conf:.0%}) ⏱ {dt:.0f}s")
        results.append({"code": code, "name": name, "sector": sector, "rating": rating, "conf": conf, "ok": True})
    except Exception as e:
        dt = time.time() - t0
        print(f"→ ❌ {str(e)[:80]} ⏱ {dt:.0f}s")
        results.append({"code": code, "name": name, "sector": sector, "rating": "ERR", "conf": 0, "ok": False})

    time.sleep(1)

print("\n" + "=" * 60)
print("📊 预测汇总")
print("-" * 40)
by_rating = {}
for r in results:
    key = r["rating"]
    by_rating[key] = by_rating.get(key, 0) + 1

for rating, cnt in sorted(by_rating.items()):
    emoji = {"Buy": "🟢", "Overweight": "🟡", "Hold": "⚪", "ERR": "❌"}.get(rating, "")
    print(f"  {emoji} {rating}: {cnt} 只")

total_t = (time.time() - start_time) / 60
print(f"\n总耗时: {total_t:.1f} 分钟")
ok_count = sum(1 for r in results if r["ok"])
print(f"成功: {ok_count}/{len(STOCKS)}")
