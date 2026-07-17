import json
from pathlib import Path
from collections import defaultdict

# (round-9, L-scripts-2): 相对路径改基于 __file__ 的绝对路径，避免 cwd 依赖
data = json.loads((Path(__file__).parent.parent / "opt" / "input" / "rollout.json").read_text(encoding="utf-8"))
print("Dates:", data["date_range"])
print()

by_date = defaultdict(lambda: {"HIT": 0, "AVOID": 0, "MISS": 0, "STEP": 0})
by_sector = defaultdict(lambda: {"HIT": 0, "AVOID": 0, "MISS": 0, "STEP": 0})

for r in data["rollout_results"]:
    d = r["date"]
    by_date[d][r["verdict"]] += 1
    if r["date"] == "2026-06-23":
        by_sector[r["sector"]][r["verdict"]] += 1

for d in sorted(by_date):
    s = by_date[d]
    total = sum(s.values())
    acc = (s["HIT"] + s["AVOID"]) / total * 100 if total else 0
    print("{}: {}只 | HIT:{} AVOID:{} MISS:{} STEP:{} | 准确率 {:.1f}%".format(
        d, total, s["HIT"], s["AVOID"], s["MISS"], s["STEP"], acc))

    step_list = [r for r in data["rollout_results"] if r["date"] == d and r["verdict"] == "STEP"]
    if step_list:
        print("  STEP 漏判:")
        for r in step_list:
            print("    {} {}({}) pred={} actual={:+.2f}%".format(
                r["stock"], r["name"], r["sector"], r["rating"], r["actual_chg"]))
    miss_list = [r for r in data["rollout_results"] if r["date"] == d and r["verdict"] == "MISS"]
    if miss_list:
        print("  MISS 踏空:")
        for r in miss_list:
            print("    {} {}({}) pred={} actual={:+.2f}%".format(
                r["stock"], r["name"], r["sector"], r["rating"], r["actual_chg"]))

# 06-23 按板块
print("\n--- 06-23 预测 → 06-24 实盘 (优化前Skills) ---")
for sector, s in sorted(by_sector.items()):
    total = sum(s.values())
    if total > 0:
        acc = (s["HIT"] + s["AVOID"]) / total * 100
        print("  {} ({}只): HIT:{} AVOID:{} MISS:{} STEP:{} | 准确率 {:.0f}%".format(
            sector, total, s["HIT"], s["AVOID"], s["MISS"], s["STEP"], acc))
