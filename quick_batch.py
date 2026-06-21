"""精简批量 — 每个方向2只，共10只"""
import sys, json, time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.resolve()))

from config.default_config import get_config
from graph.trading_graph import AStockTradingGraph
from dataflows.akshare_adapter import get_latest_trade_date

STOCKS = [
    ("600438", "通威股份", "光伏"),
    ("601012", "隆基绿能", "光伏"),
    ("002202", "金风科技", "风电"),
    ("603606", "东方电缆", "风电"),
    ("002230", "科大讯飞", "AI"),
    ("688256", "寒武纪", "AI"),
    ("300750", "宁德时代", "储能"),
    ("002460", "赣锋锂业", "储能"),
    ("002415", "海康威视", "视觉"),
    ("603501", "韦尔股份", "视觉"),
]

trade_date = get_latest_trade_date()
batch_id = datetime.now().strftime("%Y%m%d_%H%M%S")
results_dir = Path.home() / ".astock_agent" / "batch_results"
results_dir.mkdir(parents=True, exist_ok=True)

print("=" * 55)
print(f"  精简批量分析 — 10只股票")
print(f"  交易日: {trade_date}")
print("=" * 55)

config = get_config()
config["max_risk_discuss_rounds"] = 2  # 增加风险辩论轮数以获得差异化评级
agent = AStockTradingGraph(config=config, debug=False)
results = []

t_start = time.time()
for i, (code, name, sector) in enumerate(STOCKS):
    elapsed = (time.time() - t_start) / 60
    eta = (elapsed / max(i, 1)) * (len(STOCKS) - i) if i > 0 else 0
    print(f"\n{'─' * 50}")
    print(f"  [{i+1:2d}/{len(STOCKS)}] {code} {name} ({sector}) | 已用 {elapsed:.1f}分 | 预计剩余 {eta:.1f}分")

    try:
        result = agent.analyze(symbol=code, trade_date=trade_date, stock_name=name)
        result["_sector"] = sector
        result["_batch_id"] = batch_id

        out_dir = results_dir / code
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        with open(out_dir / f"{ts}_analysis.json", "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        rating = result.get("rating", "?")
        print(f"  ▶ {name}: {rating} (信心 {result.get('confidence',0):.0%})")
        results.append({"symbol": code, "name": name, "sector": sector, "rating": rating, "ok": True})
    except Exception as e:
        print(f"  ✖ {name}: {e}")
        results.append({"symbol": code, "name": name, "sector": sector, "error": str(e), "ok": False})

# 汇总
total_min = (time.time() - t_start) / 60
ok_count = sum(1 for r in results if r.get("ok"))
print(f"\n{'=' * 55}")
print(f"  完成: {ok_count}/{len(STOCKS)} | 耗时 {total_min:.1f} 分钟")
print(f"  结果: {results_dir}\\{{代码}}\\")
print(f"{'=' * 55}")

# 汇总表
print(f"\n{'赛 道':<6} {'评 级':<12} {'股票'}")
print("-" * 40)
for r in results:
    rating = r.get("rating", "ERR")
    status = "✅" if r.get("ok") else "❌"
    print(f"{r.get('sector','?'):<6} {status} {rating:<10} {r['name']}")
