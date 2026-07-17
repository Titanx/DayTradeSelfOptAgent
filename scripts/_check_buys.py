import json, re
from pathlib import Path

# (round-9, L-scripts-3): 相对路径改基于 __file__ 的绝对路径，避免 cwd 依赖
for code in ["300073", "300772", "603606"]:
    path = Path(__file__).parent.parent / "data" / "results" / f"{code}_2026-07-04_v10_analysis.cache.json"
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    dec = d.get("decision", "")
    m = re.search(r'"confidence":\s*([\d.]+)', dec)
    conf = m.group(1) if m else "?"
    m2 = re.search(r'"decision":\s*"([^"]+)"', dec)
    dec_label = m2.group(1) if m2 else "?"
    m3 = re.search(r'"reasoning":\s*"([^"]{0,300})', dec)
    reason = m3.group(1) if m3 else ""
    print(f"{code} {d['stock_name']}: {dec_label} confidence={conf}")
    if reason:
        print(f"  {reason}...")
    print()
