"""0622预测 vs 0623实盘 — 25股一日游回测"""
import json, urllib.request, time
from pathlib import Path

RESULTS_DIR = Path(__file__).parent.parent / "data" / "results"
STOCKS = [
    ("sh600438","通威股份","光伏"),("sh601012","隆基绿能","光伏"),("sz300274","阳光电源","光伏"),
    ("sh688599","天合光能","光伏"),("sz300751","迈为股份","光伏"),
    ("sz002202","金风科技","风电"),("sh601615","明阳智能","风电"),("sh603606","东方电缆","风电"),
    ("sz300850","新强联","风电"),("sz001289","龙源电力","风电"),
    ("sz002230","科大讯飞","AI"),("sh688256","寒武纪","AI"),("sz000977","浪潮信息","AI"),
    ("sz300308","中际旭创","AI"),("sz300033","同花顺","AI"),
    ("sz300750","宁德时代","储能"),("sz300014","亿纬锂能","储能"),("sz002074","国轩高科","储能"),
    ("sz002460","赣锋锂业","储能"),("sh601727","上海电气","储能"),
    ("sz002415","海康威视","视觉"),("sz002236","大华股份","视觉"),("sz002920","德赛西威","视觉"),
    ("sz300496","中科创达","视觉"),("sh603501","韦尔股份","视觉"),
]

def get_prediction(code):
    f = RESULTS_DIR / f"{code}_2026-06-22_analysis.cache.json"
    if not f.exists():
        return None
    d = json.loads(f.read_text(encoding="utf-8"))
    return d.get("rating","?"), d.get("confidence",0)

def get_kline(sid):
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sid},day,,,3,qfq"
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
    resp = urllib.request.urlopen(req, timeout=10)
    klines = json.loads(resp.read().decode("utf-8"))["data"][sid]["qfqday"]
    d0 = d1 = None
    for k in klines:
        if k[0] == "2026-06-22":
            d0 = float(k[2])
        if k[0] == "2026-06-23":
            d1 = {"open":float(k[1]),"close":float(k[2]),"high":float(k[3]),"low":float(k[4])}
    return d0, d1

def color_pct(pct):
    s = f"{pct:+.2f}%"
    if pct >= 3: return f"🔥{s}"
    if pct >= 1: return f"📈{s}"
    if pct >= 0: return f"➖{s}"
    return f"📉{s}"

print("=" * 75)
print("  一日游回测: 0622预测 → 0623收盘")
print("=" * 75)
print(f"{'代码':<8}{'名称':<8}{'板块':<6}{'预测':<14}{'信心':<6}{'开盘':<8}{'收盘':<8}{'涨跌':<12}{'开盘买':<8}{'结果'}")
print("-" * 75)

hit = avoid = miss = step_on = 0
results = []

for sid, name, sector in STOCKS:
    code = sid[2:]
    pred = get_prediction(code)
    if not pred:
        continue
    rating, conf = pred
    try:
        d0, d1 = get_kline(sid)
        time.sleep(0.1)
    except Exception as e:
        continue
    if d0 is None or d1 is None:
        continue

    close_pct = (d1["close"]/d0 - 1)*100
    open_pct = (d1["close"]/d1["open"] - 1)*100
    net_pct = open_pct - 0.11

    should_buy = rating in ("Buy","Overweight")
    actually_up = close_pct >= 1.0

    if should_buy and actually_up: verdict = "HIT 命中"
    elif should_buy: verdict = "MISS 误判"
    elif actually_up: verdict = "STEP 踏空"
    else: verdict = "AVOID 回避"

    if should_buy and actually_up: hit += 1
    elif should_buy: miss += 1
    elif actually_up: step_on += 1
    else: avoid += 1

    results.append((code, name, sector, rating, conf, d0, d1["open"], d1["close"], close_pct, open_pct, net_pct, verdict))

for r in results:
    code, name, sector, rating, conf, d0, dop, dclose, cpct, opct, net, verdict = r
    print(f"{code:<8}{name:<8}{sector:<6}{rating:<14}{conf:.0%}{'':<2}{dop:<8.2f}{dclose:<8.2f}{color_pct(cpct):<16}{color_pct(opct):<8}{verdict}")

total = hit + avoid + miss + step_on
print("\n" + "=" * 75)
print("  汇总")
print("=" * 75)
print(f"  总: {total}笔  |  HIT: {hit}  |  AVOID: {avoid}  |  MISS: {miss}  |  STEP: {step_on}")
print(f"  准确率: {(hit+avoid)/total*100:.0f}% ({hit+avoid}/{total})")
if hit+miss > 0:
    print(f"  Buy信号准确率: {hit}/{hit+miss} = {hit/(hit+miss)*100:.0f}%")
print(f"  踏空率: {step_on/total*100:.0f}%")
print(f"  误判率: {miss/total*100:.0f}%")
