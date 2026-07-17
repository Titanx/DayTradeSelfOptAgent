import json, os
from pathlib import Path

# (round-9, L-scripts-3): 相对路径改基于 __file__ 的绝对路径，避免 cwd 依赖
overview_dir = Path(__file__).parent.parent / "data" / "overview_cache"

for f in sorted(os.listdir(overview_dir)):
    if "0702" in f and f.endswith(".json"):
        with open(os.path.join(overview_dir, f), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        indices = data.get("indices", {})
        print("=== 7/2 大盘 ===")
        for k, v in indices.items():
            if isinstance(v, dict):
                print(f"  {k}: close={v.get('close','?')}  pct_chg={v.get('pct_chg','?')}")
        sentiment = data.get("market_sentiment", {})
        # (round-12, H-scripts-4): market_sentiment 存为 string（market_overview.py:73），改为尝试解析
        try:
            if isinstance(sentiment, str):
                import re
                up_match = re.search(r'up_count["\s:]+(\d+)', sentiment)
                down_match = re.search(r'down_count["\s:]+(\d+)', sentiment)
                if up_match and down_match:
                    print(f"  up={up_match.group(1)} down={down_match.group(1)}")
            elif isinstance(sentiment, dict):
                print(f"  up={sentiment.get('up_count','?')} down={sentiment.get('down_count','?')}")
        except Exception:
            pass
        break

print()
for f in sorted(os.listdir(overview_dir)):
    if "0704" in f and f.endswith(".json"):
        with open(os.path.join(overview_dir, f), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        indices = data.get("indices", {})
        print("=== 7/4 大盘 ===")
        for k, v in indices.items():
            if isinstance(v, dict):
                print(f"  {k}: close={v.get('close','?')}  pct_chg={v.get('pct_chg','?')}")
        sentiment = data.get("market_sentiment", {})
        # (round-12, H-scripts-4): market_sentiment 存为 string（market_overview.py:73），改为尝试解析
        try:
            if isinstance(sentiment, str):
                import re
                up_match = re.search(r'up_count["\s:]+(\d+)', sentiment)
                down_match = re.search(r'down_count["\s:]+(\d+)', sentiment)
                if up_match and down_match:
                    print(f"  up={up_match.group(1)} down={down_match.group(1)}")
            elif isinstance(sentiment, dict):
                print(f"  up={sentiment.get('up_count','?')} down={sentiment.get('down_count','?')}")
        except Exception:
            pass
        break
