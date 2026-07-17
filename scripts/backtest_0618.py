"""一日游回测: Day0(0618) → Day1(0619) → 今日(0622)"""
import json, urllib.request
from pathlib import Path

results_dir = Path(__file__).parent.parent / "data" / "results"

STOCKS = [
    ("sz300750", "宁德时代"),
    ("sh600438", "通威股份"),
    ("sz300033", "同花顺"),
    ("sz002202", "金风科技"),
    ("sz002415", "海康威视"),
]

def get_0618_prediction(code):
    files = sorted(results_dir.glob(f"{code}_*_analysis.cache.json"))
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        if "2026-06-18" in data.get("trade_date", ""):
            return data
    return None

def get_kline_data(sid):
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sid},day,,,5,qfq"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    resp = urllib.request.urlopen(req, timeout=10)
    data = json.loads(resp.read().decode("utf-8"))
    return data["data"][sid]["qfqday"]

print("=" * 72)
print("  一日游回测: Day0(0618分析) → 今日(0622实盘)")
print("=" * 72)

for sid, name in STOCKS:
    pure_code = sid[2:]
    pred = get_0618_prediction(pure_code)
    if not pred:
        print(f"\n  {pure_code} {name}: 无0618预测数据")
        continue

    try:
        klines = get_kline_data(sid)
    except Exception as e:
        print(f"\n  {pure_code} {name}: K线获取失败 - {e}")
        continue

    d0_close = d1_close = d1_open = d1_high = d1_low = None
    d1_date = None
    for k in klines:
        if k[0] == "2026-06-18":
            d0_close = float(k[2])
        # 找0622及之后的第一天 (0619可能是周六/端午/周末)
        if k[0] >= "2026-06-19":
            if d1_close is None:
                d1_date = k[0]
                d1_open = float(k[1])
                d1_close = float(k[2])
                d1_high = float(k[3])
                d1_low = float(k[4])
                break

    if d0_close is None:
        print(f"\n  {pure_code} {name}: 无0618收盘价")
        continue
    if d1_close is None:
        print(f"\n  {pure_code} {name}: 无0618之后的交易日数据")
        continue

    rating = pred.get("rating", "?")
    confidence = pred.get("confidence", 0)
    summary = (pred.get("summary") or pred.get("executive_summary") or "")[:100]

    close_pct = (d1_close / d0_close - 1) * 100
    open_pct = (d1_close / d1_open - 1) * 100
    net_pct = open_pct - 0.11

    should_buy = rating in ("Buy", "Overweight")
    actually_up = close_pct >= 1.0

    if should_buy and close_pct >= 1.0:
        verdict = "HIT 命中"
    elif should_buy:
        verdict = "MISS 误判"
    elif close_pct >= 1.0:
        verdict = "STEP 踏空"
    else:
        verdict = "AVOID 正确回避"

    print(f"\n  {'─' * 50}")
    print(f"  {pure_code} {name}")
    print(f"  {'─' * 50}")
    print(f"  预测(0618): {rating:12s}  信心: {confidence:.0%}")
    print(f"  逻辑: {summary}")
    print(f"  0618收盘:  {d0_close:.2f}")
    print(f"  {d1_date}区间: 开{d1_open:.2f} 收{d1_close:.2f} (高{d1_high:.2f} 低{d1_low:.2f})")
    print(f"  涨跌幅:    {close_pct:+.2f}%")
    print(f"  开盘买入:  {open_pct:+.2f}% (净: {net_pct:+.2f}%)")
    print(f"  结果:      {verdict}")

# 汇总
print("\n" + "=" * 72)
print("  回测汇总")
print("=" * 72)

hit = avoid = miss = step_on = 0
for sid, name in STOCKS:
    pure_code = sid[2:]
    pred = get_0618_prediction(pure_code)
    if not pred:
        continue
    try:
        klines = get_kline_data(sid)
    except Exception:
        continue

    d0_close = d1_close = None
    for k in klines:
        if k[0] == "2026-06-18":
            d0_close = float(k[2])
        if d1_close is None and k[0] > "2026-06-19":
            d1_close = float(k[2])
            break
    if d0_close is None or d1_close is None:
        continue

    close_pct = (d1_close / d0_close - 1) * 100
    should_buy = pred.get("rating") in ("Buy", "Overweight")

    if should_buy and close_pct >= 1.0:
        hit += 1
    elif should_buy:
        miss += 1
    elif close_pct >= 1.0:
        step_on += 1
    else:
        avoid += 1

total = hit + avoid + miss + step_on
if total:
    print(f"  标的: {total} 支")
    print(f"  命中 (Buy→涨1%+):  {hit}")
    print(f"  正确回避 (Hold→不达标): {avoid}")
    print(f"  误判 (Buy→跌/不达标):  {miss}")
    print(f"  踏空 (Hold→涨1%+):    {step_on}")
    print(f"  准确率: {(hit+avoid)/total*100:.0f}% ({hit+avoid}/{total})")
