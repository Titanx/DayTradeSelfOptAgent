import json
from pathlib import Path

results_dir = Path(__file__).parent.parent / "data" / "results"
files = sorted(results_dir.glob("*_analysis.cache.json"))

print(f"总计: {len(files)}/25 完成\n")

by_sector = {}
by_rating = {}
for f in files:
    d = json.loads(f.read_text(encoding="utf-8"))
    s = d["symbol"]
    rating = d["rating"]
    stock_name = d.get("stock_name", "")
    conf = d["confidence"]
    sector = "未知"
    by_rating.setdefault(rating, []).append(f"{s} {stock_name}")
    print(f"{s} {stock_name:6s}  {rating:12s}  {conf:.0%}")

print("\n=== 按评级汇总 ===")
for k, v in sorted(by_rating.items()):
    emoji = {"Buy": "🟢", "Overweight": "🟡", "Hold": "⚪", "Underweight": "🟠", "Sell": "🔴"}.get(k, "❓")
    print(f"\n{emoji} {k} ({len(v)}支):")
    for s in v:
        print(f"    {s}")
